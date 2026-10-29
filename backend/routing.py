"""
Risk-aware route calculation.

The prototype contains a primary route and a genuine alternate
route through different road segments.

Production version:
- Road network -> PostGIS
- Live incidents -> government/API feeds
- Weather -> live weather API
- Risk -> trained ML model
"""

from pathlib import Path
import json
import math
import networkx as nx


GEOJSON_PATH = Path(__file__).parent / "data" / "road_network.geojson"


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


def load_geojson():
    """Load the road network GeoJSON."""

    if not GEOJSON_PATH.exists():
        return None

    with open(GEOJSON_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def build_graph():
    """Build a NetworkX road graph from GeoJSON."""

    geojson = load_geojson()

    graph = nx.Graph()

    if not geojson:
        return graph

    for feature in geojson.get("features", []):

        geometry = feature.get("geometry", {})

        if geometry.get("type") != "LineString":
            continue

        coordinates = geometry.get("coordinates", [])

        properties = feature.get("properties", {})

        risk = float(properties.get("risk", 20))

        road_name = properties.get(
            "name",
            "Unnamed Road"
        )

        road_type = properties.get(
            "route_type",
            "alternate"
        )

        for i in range(len(coordinates) - 1):

            start = tuple(coordinates[i])
            end = tuple(coordinates[i + 1])

            distance = haversine_distance(
                start,
                end
            )

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
        "coordinates": [
            list(node)
            for node in path
        ],
        "distance_km": round(
            total_distance,
            2
        ),
        "risk_score": round(
            average_risk,
            2
        ),
    }


def calculate_route(
    start,
    destination,
    avoid_high_risk=False
):
    """
    Calculate a route.

    Normal mode:
        Prefer the designated primary route.

    Safer mode:
        Penalize high-risk roads heavily so the algorithm
        searches for a genuinely safer alternative.
    """

    graph = build_graph()

    if graph.number_of_nodes() == 0:
        return {
            "coordinates": [],
            "distance_km": 0,
            "risk_score": 0,
            "route_type": "unknown",
        }

    start_node = nearest_node(
        graph,
        start
    )

    destination_node = nearest_node(
        graph,
        destination
    )

    if start_node is None or destination_node is None:
        return {
            "coordinates": [],
            "distance_km": 0,
            "risk_score": 0,
            "route_type": "unknown",
        }

    # --------------------------------------------------
    # NORMAL ROUTE
    # --------------------------------------------------

    if not avoid_high_risk:

        primary_edges = [
            (
                u,
                v,
                data
            )
            for u, v, data
            in graph.edges(data=True)
            if data.get("route_type") == "primary"
        ]

        primary_graph = nx.Graph()

        for u, v, data in primary_edges:

            primary_graph.add_edge(
                u,
                v,
                distance=data["distance"],
                risk=data["risk"],
                road=data["road"],
                route_type=data["route_type"],
            )

        try:

            path = nx.shortest_path(
                primary_graph,
                start_node,
                destination_node,
                weight="distance",
            )

            result = get_path_details(
                primary_graph,
                path
            )

            result["route_type"] = "primary"

            return result

        except nx.NetworkXNoPath:

            # Fallback if the primary network is incomplete
            pass

    # --------------------------------------------------
    # SAFER ROUTE
    # --------------------------------------------------

    route_graph = graph.copy()

    for u, v, data in route_graph.edges(
        data=True
    ):

        distance = data["distance"]
        risk = data["risk"]

        if avoid_high_risk:

            # Strong penalty for risky roads.
            #
            # Example:
            # risk 80 -> huge routing cost
            # risk 20 -> relatively small cost
            #
            data["routing_cost"] = (
                distance
                * (
                    1
                    + (risk / 100) * 12
                )
            )

        else:

            data["routing_cost"] = distance

    try:

        path = nx.shortest_path(
            route_graph,
            start_node,
            destination_node,
            weight="routing_cost",
        )

    except nx.NetworkXNoPath:

        return {
            "coordinates": [],
            "distance_km": 0,
            "risk_score": 0,
            "route_type": "none",
        }

    result = get_path_details(
        route_graph,
        path
    )

    result["route_type"] = (
        "safer_alternate"
        if avoid_high_risk
        else "primary"
    )

    return result


def get_routes():
    """Return primary and AI-recommended safer routes."""

    start = [
        91.8933,
        25.5788
    ]

    destination = [
        91.7033,
        25.267
    ]

    normal_route = calculate_route(
        start,
        destination,
        avoid_high_risk=False,
    )

    safer_route = calculate_route(
        start,
        destination,
        avoid_high_risk=True,
    )

    return {
        "normal": normal_route,
        "safer": safer_route,
    }