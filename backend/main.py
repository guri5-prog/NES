from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import json
from pathlib import Path

from data_gen import (
    get_vehicles,
    get_weather,
    get_incidents,
)

from risk_model import predict_risk
from routing import get_routes


app = FastAPI(
    title="AI Smart Logistics API",
    description="Risk-aware logistics routing prototype",
    version="1.0"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# SIMULATED IN-MEMORY INCIDENT STORE
# ============================================================

active_incidents = get_incidents().copy()


# ============================================================
# INCIDENT MODEL
# ============================================================

class IncidentCreate(BaseModel):
    type: str
    severity: str
    description: str
    lat: Optional[float] = None
    lon: Optional[float] = None


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():
    return {
        "message": "AI Smart Logistics API is running",
        "status": "OK"
    }


# ============================================================
# VEHICLES
# ============================================================

@app.get("/api/vehicles")
def vehicles():

    return get_vehicles()


# ============================================================
# WEATHER
# ============================================================

@app.get("/api/weather")
def weather():

    return get_weather()


# ============================================================
# INCIDENTS
# ============================================================

@app.get("/api/incidents")
def incidents():

    return {
        "incidents": active_incidents
    }


@app.post("/api/incidents")
def create_incident(incident: IncidentCreate):

    new_incident = {
        "id": f"INC-{len(active_incidents) + 1:03d}",
        "type": incident.type,
        "severity": incident.severity,
        "description": incident.description,
        "lat": incident.lat,
        "lon": incident.lon,
        "timestamp": datetime.now().isoformat(),
        "source": "USER_REPORTED"
    }

    active_incidents.append(new_incident)

    return {
        "message": "Incident registered successfully",
        "incident": new_incident
    }


# ============================================================
# AI RISK
# ============================================================

@app.get("/api/risk")
def risk():

    features = {
        "rainfall": 42.5,
        "visibility": 3.2,
        "traffic": 0.65,
        "slope": 0.72,
    }

    prediction = predict_risk(features)

    # --------------------------------------------------------
    # INCIDENT IMPACT
    # --------------------------------------------------------

    incident_boost = 0

    for incident in active_incidents:

        if incident["severity"].upper() == "HIGH":

            incident_boost += 20

        elif incident["severity"].upper() == "MEDIUM":

            incident_boost += 10

    prediction["score"] = min(
        100,
        round(
            prediction["score"] + incident_boost,
            2
        )
    )

    # Recalculate risk level
    if prediction["score"] >= 70:
        prediction["level"] = "HIGH"

    elif prediction["score"] >= 40:
        prediction["level"] = "MEDIUM"

    else:
        prediction["level"] = "LOW"


    return {
        "features": features,
        "prediction": prediction,
        "incident_impact": incident_boost,
    }


# ============================================================
# ROUTES
# ============================================================

@app.get("/api/routes")
def routes():

    route_data = get_routes()

    primary_risk = route_data["normal"]["risk_score"]

    # --------------------------------------------------------
    # If a high-severity incident is reported,
    # increase the primary route risk.
    # --------------------------------------------------------

    for incident in active_incidents:

        if incident["severity"].upper() == "HIGH":

            primary_risk = min(
                100,
                primary_risk + 13
            )

            break


    route_data["normal"]["risk_score"] = primary_risk


    # --------------------------------------------------------
    # Safer route remains available
    # --------------------------------------------------------

    if primary_risk >= 70:

        route_data["recommendation"] = {
            "recommended": True,
            "reason": "High-risk incident detected on the primary corridor.",
            "route": "safer"
        }

    else:

        route_data["recommendation"] = {
            "recommended": False,
            "reason": "Primary route currently within acceptable risk.",
            "route": "normal"
        }


    return route_data


# ============================================================
# ROAD NETWORK
# ============================================================

@app.get("/api/network")
def network():

    network_file = (
        Path(__file__).parent
        / "data"
        / "road_network.geojson"
    )

    with open(
        network_file,
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(file)