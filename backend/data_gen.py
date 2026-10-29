"""
Demo data generator for the Shillong–Cherrapunji logistics prototype.

This generates:
- simulated vehicles
- weather conditions
- road incidents
- risk features

No physical GPS hardware or government API is required.
"""

from datetime import datetime
import random
import math


# Approximate coordinates around the Shillong–Cherrapunji corridor.
# Format: [longitude, latitude]
SHILLONG = [91.8933, 25.5788]
MAWPHLANG = [91.7610, 25.4030]
SOHRA = [91.7033, 25.2670]

# Demo vehicle locations
VEHICLES = [
    {
        "id": "TRUCK-101",
        "driver": "Vehicle A",
        "cargo": "Essential Supplies",
        "lat": 25.492,
        "lon": 91.825,
        "speed": 38,
        "status": "moving",
    },
    {
        "id": "TRUCK-102",
        "driver": "Vehicle B",
        "cargo": "Medical Supplies",
        "lat": 25.410,
        "lon": 91.770,
        "speed": 31,
        "status": "moving",
    },
    {
        "id": "TRUCK-103",
        "driver": "Vehicle C",
        "cargo": "Food Supplies",
        "lat": 25.535,
        "lon": 91.855,
        "speed": 0,
        "status": "warning",
    },
]


def get_vehicles():
    """
    Return simulated vehicle telemetry.
    """

    vehicles = []

    for vehicle in VEHICLES:
        vehicle_copy = vehicle.copy()

        # Small simulated movement
        if vehicle_copy["status"] == "moving":
            vehicle_copy["lat"] += random.uniform(-0.001, 0.001)
            vehicle_copy["lon"] += random.uniform(-0.001, 0.001)

            vehicle_copy["speed"] = max(
                10,
                min(60, vehicle_copy["speed"] + random.randint(-3, 3))
            )

        vehicles.append(vehicle_copy)

    return {
        "timestamp": datetime.now().isoformat(),
        "vehicles": vehicles,
    }


def get_weather():
    """
    Simulated weather feed.

    In production this can be replaced by a real weather API.
    """

    return {
        "rainfall_mm": 42.5,
        "visibility_km": 3.2,
        "temperature_c": 18.4,
        "humidity": 91,
        "condition": "Heavy Rain",
        "source": "SIMULATED",
        "timestamp": datetime.now().isoformat(),
    }


def get_incidents():
    """
    Simulated road incidents.
    """

    return [
        {
            "id": "INC-001",
            "type": "LANDSLIDE_RISK",
            "severity": "HIGH",
            "lat": 25.365,
            "lon": 91.735,
            "description": "Heavy rainfall increasing landslide probability.",
        },
        {
            "id": "INC-002",
            "type": "LOW_VISIBILITY",
            "severity": "MEDIUM",
            "lat": 25.455,
            "lon": 91.790,
            "description": "Visibility reduced due to rain and fog.",
        },
    ]


def generate_risk_features():
    """
    Generate a feature vector for the AI risk model.
    """

    rainfall = 42.5
    visibility = 3.2
    traffic = 0.65
    slope = 0.72

    return {
        "rainfall": rainfall,
        "visibility": visibility,
        "traffic": traffic,
        "slope": slope,
    }