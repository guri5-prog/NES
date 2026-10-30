
"""
Risk-aware route calculation.

Road network is retrieved from PostgreSQL/PostGIS.
NetworkX is used to calculate primary and safer routes.
"""

import math
import json
import networkx as nx

from sqlalchemy.orm import Session
from sqlalchemy import func

from models import Road


def haversine_distance(a, b):
    """Calculate distance between [lon, lat] points in kilometres."""

    lon1, lat1 = a
    lon2, lat2 = b

    R = 6371

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    value = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(d_lambda / 2) ** 2
    )

    return R * 2 * math.atan2(
        math.sqrt(value),
        math.sqrt(1 - value),
    )


def build_graph(db: Session):
    """Build a NetworkX graph using road data from PostGIS."""

    graph = nx.Graph()

    roads = db.query(
        Road.name,
        Road.risk,
        Road.route_type,
        func.ST_AsGeoJSON(Road.geom).label("geometry")
    ).filter(Road.geom.isnot(None)).all()

    for road in roads:

        if not road.geometry:
            continue

        geometry = json.loads(road.geometry)

        if geometry.get("type") != "LineString":
            continue

        coordinates = geometry.get("coordinates", [])

        risk = float(road.risk or 0)
        road_name = road.name or "Unnamed Road"
        road_type = road.route_type or "alternate"

        for i in range(len(coordinates) - 1):

            start = tuple(coordinates[i])
            end = tuple(coordinates[i + 1])

            distance = haversine_distance(start, end)

            graph.add_node(start)
            graph.add_node(end)

            graph.add_edge(
                start,
                end,
                distance=distance,
                risk=risk,
                road=road_name,
                route_type=road_type,
            )

    return graph


def nearest_node(graph, coordinate):
    """Find the closest graph node."""

    if graph.number_of_nodes() == 0:
        return None

    return min(
        graph.nodes,
        key=lambda node: haversine_distance(
            node,
            coordinate
        )
    )


def get_path_details(graph, path):
    """Calculate distance and risk for a path."""

    total_distance = 0
    risks = []

    for u, v in zip(path[:-1], path[1:]):

        edge = graph[u][v]

        total_distance += edge["distance"]
        risks.append(edge["risk"])

    average_risk = (
        sum(risks) / len(risks)
        if risks
        else 0
    )

    return {
        "coordinates": [list(node) for node in path],
        "distance_km": round(total_distance, 2),
        "risk_score": round(average_risk, 2),
    }


def calculate_route(
    db: Session,
    start,
    destination,
    avoid_high_risk=False
):
    """Calculate a route using the PostGIS road network."""

    graph = build_graph(db)

    if graph.number_of_nodes() == 0:
        return {
            "coordinates": [],
            "distance_km": 0,
            "risk_score": 0,
            "route_type": "unknown",
        }

    start_node = nearest_node(graph, start)
    destination_node = nearest_node(graph, destination)

    if start_node is None or destination_node is None:
        return {
            "coordinates": [],
            "distance_km": 0,
            "risk_score": 0,
            "route_type": "unknown",
        }

    # Normal route: prefer primary roads.

    if not avoid_high_risk:

        primary_graph = nx.Graph()

        for u, v, data in graph.edges(data=True):

            if data.get("route_type") == "primary":

                primary_graph.add_edge(
                    u,
                    v,
                    **data
                )

        try:

            path = nx.shortest_path(
                primary_graph,
                start_node,
                destination_node,
                weight="distance",
            )

            result = get_path_details(primary_graph, path)
            result["route_type"] = "primary"

            return result

        except (nx.NetworkXNoPath, nx.NodeNotFound):
            pass

    # Safer route: penalize roads with higher risk.

    route_graph = graph.copy()

    for u, v, data in route_graph.edges(data=True):

        distance = data["distance"]
        risk = data["risk"]

        data["routing_cost"] = (
            distance * (1 + (risk / 100) * 12)
        )

    try:

        path = nx.shortest_path(
            route_graph,
            start_node,
            destination_node,
            weight="routing_cost",
        )

    except (nx.NetworkXNoPath, nx.NodeNotFound):

        return {
            "coordinates": [],
            "distance_km": 0,
            "risk_score": 0,
            "route_type": "none",
        }

    result = get_path_details(route_graph, path)

    result["route_type"] = (
        "safer_alternate"
        if avoid_high_risk
        else "primary"
    )

    return result


def get_routes(db: Session):
    """Return primary and safer routes using database roads."""

    start = [91.8933, 25.5788]
    destination = [91.7033, 25.267]

    normal_route = calculate_route(
        db,
        start,
        destination,
        avoid_high_risk=False,
    )

    safer_route = calculate_route(
        db,
        start,
        destination,
        avoid_high_risk=True,
    )

    return {
        "normal": normal_route,
        "safer": safer_route,
    }
