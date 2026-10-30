"""
Risk-Aware Route Calculation for SETU-NER.

Calculates optimal routes using a multi-factor cost function:
    C(e) = alpha * D(e) + beta * R(e)

Where:
    - C(e): Total routing cost of traversing road segment e
    - D(e): Distance of the road segment in kilometres (Haversine formula)
    - R(e): Normalized, uncalibrated heuristic disruption indicator
    - alpha: Weight assigned to distance (default: 1.0)
    - beta: Weight assigned to risk (0.0 for pure shortest path, 25.0 for safer path)

For a complete path P:
    C(P) = sum_{e in P} [alpha * D(e) + beta * R(e)]
"""

import json
import math
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import networkx as nx
from sqlalchemy.orm import Session
from sqlalchemy import func

from models import Road, Incident, Weather
from risk_model import calculate_segment_risk

logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parent.parent
LOCAL_GEOJSON_PATH = PROJECT_DIR / "Dataset" / "data" / "raw" / "roads" / "sikkim_roads.geojson"
_LOCAL_ROADS_CACHE: Optional[List[Dict[str, Any]]] = None


def haversine_distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """Calculate geodesic distance between two [lon, lat] points in kilometres."""
    lon1, lat1 = a
    lon2, lat2 = b

    R = 6371.0  # Earth radius in km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    val = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    return R * 2.0 * math.atan2(math.sqrt(val), math.sqrt(max(0.0, 1.0 - val)))


def load_roads_dataset(db: Optional[Session] = None) -> List[Dict[str, Any]]:
    """Load Sikkim source roads; opt in to PostGIS roads after importing that same network."""
    global _LOCAL_ROADS_CACHE
    roads_list = []
    if db is not None and os.getenv("ROUTE_NETWORK_SOURCE", "sikkim_geojson").lower() == "postgis":
        try:
            roads = db.query(
                Road.id,
                Road.name,
                Road.risk,
                Road.route_type,
                func.ST_AsGeoJSON(Road.geom).label("geometry")
            ).filter(Road.geom.isnot(None)).all()
            for r in roads:
                if r.geometry:
                    roads_list.append({
                        "id": r.id,
                        "name": r.name,
                        "risk": r.risk,
                        "route_type": r.route_type,
                        "geometry": r.geometry,
                    })
            if roads_list:
                return roads_list
        except Exception as e:
            logger.debug("Database road query failed (%s), falling back to local GeoJSON", e)

    # The default pilot network comes from the checked-in Sikkim OSM GeoJSON.
    if _LOCAL_ROADS_CACHE is not None:
        return _LOCAL_ROADS_CACHE
    if LOCAL_GEOJSON_PATH.exists():
        try:
            with open(LOCAL_GEOJSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                for idx, feat in enumerate(data.get("features", [])):
                    roads_list.append({
                        "id": feat.get("properties", {}).get("osmid", idx + 1),
                        "name": feat.get("properties", {}).get("name") or feat.get("properties", {}).get("ref") or f"{feat.get('properties', {}).get('highway', 'Road')} {idx+1}",
                        "risk": feat.get("properties", {}).get("risk", 0.0),
                        "route_type": feat.get("properties", {}).get("highway", "road"),
                        "oneway": feat.get("properties", {}).get("oneway", False),
                        "geometry": json.dumps(feat.get("geometry", {})),
                    })
        except Exception as err:
            logger.error("Failed to read local road network: %s", err)
        _LOCAL_ROADS_CACHE = roads_list
        return roads_list
    return roads_list


def build_risk_aware_graph(
    db: Optional[Session] = None,
    alpha: float = 1.0,
    beta: float = 25.0,
    active_incidents: Optional[List[Dict[str, Any]]] = None,
    weather_context: Optional[Dict[str, Any]] = None,
) -> nx.Graph:
    """
    Build a NetworkX road graph from PostGIS road geometries (or local GeoJSON fallback).
    Evaluates a heuristic indicator and edge cost: C(e) = alpha * D(e) + beta * R(e).
    """
    graph = nx.DiGraph()
    roads = load_roads_dataset(db)

    # Environmental features
    rainfall_value = weather_context.get("rainfall_mm") if weather_context else None
    visibility_value = weather_context.get("visibility_km") if weather_context else None
    rainfall = float(rainfall_value) if rainfall_value is not None else 0.0
    visibility = float(visibility_value) if visibility_value is not None else 10.0

    for road in roads:
        raw_geom = road.get("geometry")
        if not raw_geom:
            continue

        try:
            geom = json.loads(raw_geom) if isinstance(raw_geom, str) else raw_geom
        except Exception:
            continue

        if geom.get("type") != "LineString":
            continue

        coordinates = geom.get("coordinates", [])
        base_risk = float(road.get("risk") or 0.0)
        road_name = road.get("name") or "Unnamed Road"
        road_type = road.get("route_type") or "alternate"

        for i in range(len(coordinates) - 1):
            start = tuple(coordinates[i])
            end = tuple(coordinates[i + 1])
            distance = haversine_distance(start, end)
            segment_id = f"OSM-{road.get('id')}-{i+1}"
            midpoint = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
            nearby_incidents = [incident for incident in (active_incidents or [])
                if incident.get("lon") is not None and incident.get("lat") is not None
                and haversine_distance(midpoint, (float(incident["lon"]), float(incident["lat"]))) <= 2.0]

            # This is an uncalibrated heuristic indicator until labeled disruption
            # training data and per-road feature extraction are available.
            risk_info = calculate_segment_risk(
                segment_id=segment_id,
                base_risk=base_risk,
                rainfall_mm=rainfall,
                visibility_km=visibility,
                slope_deg=0.0,
                active_incidents=nearby_incidents,
            )

            # R(e) = risk probability (0.0 to 1.0)
            p_e = risk_info["risk_probability"]

            # Edge Cost: C(e) = alpha * D(e) + beta * R(e)
            cost_e = alpha * distance + beta * p_e

            graph.add_node(start)
            graph.add_node(end)
            edge_attributes = dict(
                segment_id=segment_id,
                distance=distance,
                risk=risk_info["score"],
                risk_probability=p_e,
                risk_level=risk_info["risk_level"],
                risk_factors=risk_info["risk_factors"],
                cost=cost_e,
                road=road_name,
                route_type=road_type,
            )
            graph.add_edge(start, end, **edge_attributes)
            oneway_value = road.get("oneway", False)
            oneway = oneway_value is True or str(oneway_value).strip().lower() in {"yes", "true", "1"}
            if not oneway:
                graph.add_edge(end, start, **edge_attributes)

    return graph


def nearest_node(graph: nx.Graph, coordinate: List[float]) -> Optional[Tuple[float, float]]:
    """Find the closest node in the road network graph."""
    if graph.number_of_nodes() == 0:
        return None

    coord_tuple = tuple(coordinate)
    return min(
        graph.nodes,
        key=lambda node: haversine_distance(node, coord_tuple)
    )


def get_path_metrics(graph: nx.Graph, path: List[Tuple[float, float]], alpha: float, beta: float) -> Dict[str, Any]:
    """Calculate aggregated route cost, distance, and segment-level risks."""
    total_distance = 0.0
    total_cost = 0.0
    probabilities = []
    risks = []
    all_factors = []
    segments_summary = []

    for u, v in zip(path[:-1], path[1:]):
        edge = graph[u][v]
        d = edge["distance"]
        p = edge["risk_probability"]
        c = alpha * d + beta * p

        total_distance += d
        total_cost += c
        probabilities.append(p)
        risks.append(edge["risk"])
        all_factors.extend(edge["risk_factors"])

        segments_summary.append({
            "segment_id": edge["segment_id"],
            "road": edge["road"],
            "distance_km": round(d, 2),
            "risk_probability": None,
            "risk_indicator": round(edge["risk"], 2),
            "risk_level": edge["risk_level"],
            "risk_factors": edge["risk_factors"],
            "cost": round(c, 2),
        })

    avg_p = sum(probabilities) / len(probabilities) if probabilities else 0.0
    avg_risk = sum(risks) / len(risks) if risks else 0.0

    if avg_p >= 0.65:
        overall_level = "HIGH"
    elif avg_p >= 0.35:
        overall_level = "MEDIUM"
    else:
        overall_level = "LOW"

    return {
        "coordinates": [list(node) for node in path],
        "distance_km": round(total_distance, 2),
        "total_cost": round(total_cost, 2),
        "risk_score": round(avg_risk, 2),
        "risk_probability": None,
        "risk_indicator": round(avg_risk, 2),
        "risk_level": overall_level,
        "risk_factors": list(dict.fromkeys(all_factors)),
        "cost_parameters": {"alpha": alpha, "beta": beta},
        "segments": segments_summary,
    }


def calculate_cost_optimized_route(
    db: Optional[Session],
    start: List[float],
    destination: List[float],
    alpha: float = 1.0,
    beta: float = 25.0,
    active_incidents: Optional[List[Dict[str, Any]]] = None,
    weather_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Computes route with minimum total cost: C(P) = sum [alpha * D(e) + beta * R(e)].
    """
    graph = build_risk_aware_graph(
        db=db,
        alpha=alpha,
        beta=beta,
        active_incidents=active_incidents,
        weather_context=weather_context,
    )

    if graph.number_of_nodes() == 0:
        return {
            "coordinates": [],
            "distance_km": 0,
            "total_cost": 0,
            "risk_score": None,
            "risk_probability": None,
            "risk_indicator": None,
            "risk_level": "UNKNOWN",
            "risk_factors": [],
            "route_type": "none",
            "segments": [],
        }

    start_node = nearest_node(graph, start)
    dest_node = nearest_node(graph, destination)

    if not start_node or not dest_node:
        return {
            "coordinates": [],
            "distance_km": 0,
            "total_cost": 0,
            "risk_score": None,
            "risk_probability": None,
            "risk_indicator": None,
            "risk_level": "UNKNOWN",
            "risk_factors": [],
            "route_type": "none",
            "segments": [],
        }

    try:
        path = nx.shortest_path(
            graph,
            start_node,
            dest_node,
            weight="cost",
        )
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return {
            "coordinates": [],
            "distance_km": 0,
            "total_cost": 0,
            "risk_score": None,
            "risk_probability": None,
            "risk_indicator": None,
            "risk_level": "UNKNOWN",
            "risk_factors": [],
            "route_type": "none",
            "segments": [],
        }

    details = get_path_metrics(graph, path, alpha, beta)
    details["route_type"] = "safer" if beta > 0.0 else "primary"
    return details


def get_routes(
    db: Optional[Session] = None,
    alpha: float = 1.0,
    beta: float = 25.0,
    start: Optional[List[float]] = None,
    destination: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """
    Computes both distance-only and heuristic risk-penalized corridors.
    """
    incidents = []
    weather_ctx = {"rainfall_mm": 0.0, "visibility_km": 10.0}

    if db is not None:
        try:
            incidents_db = db.query(
                Incident,
                func.ST_Y(Incident.geom).label("lat"),
                func.ST_X(Incident.geom).label("lon"),
            ).filter(Incident.geom.isnot(None)).all()
            incidents = [{"id": inc.incident_code, "type": inc.type, "severity": inc.severity,
                "description": inc.description, "lat": lat, "lon": lon}
                for inc, lat, lon in incidents_db if lat is not None and lon is not None
                and 87.0 <= lon <= 90.0 and 26.0 <= lat <= 29.0]
        except Exception:
            pass

        try:
            latest_weather = db.query(Weather).order_by(Weather.timestamp.desc()).first()
            if latest_weather:
                weather_ctx = {
                    "rainfall_mm": latest_weather.rainfall or 0.0,
                    "visibility_km": latest_weather.visibility if latest_weather.visibility is not None else 10.0,
                }
        except Exception:
            pass

    # Gangtok to Namchi pilot endpoints (GeoJSON coordinates are [longitude, latitude]).
    start = start or [88.6138, 27.3389]
    destination = destination or [88.3639, 27.1667]

    # Primary route: Pure shortest distance (alpha=1.0, beta=0.0)
    normal_route = calculate_cost_optimized_route(
        db=db,
        start=start,
        destination=destination,
        alpha=alpha,
        beta=0.0,
        active_incidents=incidents,
        weather_context=weather_ctx,
    )

    # Safer route: Risk-penalized shortest cost (alpha=1.0, beta=beta)
    safer_route = calculate_cost_optimized_route(
        db=db,
        start=start,
        destination=destination,
        alpha=alpha,
        beta=beta,
        active_incidents=incidents,
        weather_context=weather_ctx,
    )

    # Recommendation heuristic
    primary_risk = normal_route.get("risk_score") or 0
    route_available = bool(normal_route.get("coordinates"))
    is_recommended = route_available and primary_risk >= 50

    return {
        "normal": normal_route,
        "safer": safer_route,
        "cost_function": {
            "formula": "C(e) = alpha * D(e) + beta * R(e)",
            "alpha": alpha,
            "beta": beta,
            "risk_metric": "normalized heuristic incident/environment index (not a calibrated disruption probability)",
        },
        "recommendation": {
            "recommended": is_recommended,
            "reason": (
                f"High heuristic indicator ({primary_risk}/100) on the primary corridor due to "
                + ", ".join(normal_route.get("risk_factors", ["environmental hazards"])[:2])
                if is_recommended
                else ("No connected route was found for the requested endpoints." if not route_available
                      else "Primary route is currently within acceptable heuristic indicator margins.")
            ),
            "route": "safer" if is_recommended else "normal",
        },
    }
