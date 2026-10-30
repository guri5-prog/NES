from fastapi import Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import Road, Incident, Vehicle, Weather
from geoalchemy2 import WKTElement
from fastapi import HTTPException

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

# active_incidents = get_incidents().copy()


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
# VEHICLES - POSTGRESQL INTEGRATION
# ============================================================

@app.get("/api/vehicles")
def vehicles(db: Session = Depends(get_db)):

    try:

        # Generate simulated vehicle telemetry
        vehicle_data = get_vehicles()

        # Insert new vehicles or update existing records
        for item in vehicle_data["vehicles"]:

            vehicle = db.query(Vehicle).filter_by(
                vehicle_code=item["id"]
            ).first()

            if vehicle is None:
                vehicle = Vehicle(
                    vehicle_code=item["id"]
                )
                db.add(vehicle)

            vehicle.driver = item["driver"]
            vehicle.cargo = item["cargo"]
            vehicle.speed = item["speed"]
            vehicle.status = item["status"]

            # Store geographical location in PostGIS
            vehicle.geom = WKTElement(
                f'POINT({item["lon"]} {item["lat"]})',
                srid=4326
            )

        db.commit()

        # Retrieve the saved vehicle records from PostgreSQL
        records = db.query(
            Vehicle.vehicle_code,
            Vehicle.driver,
            Vehicle.cargo,
            Vehicle.speed,
            Vehicle.status,
            func.ST_Y(Vehicle.geom).label("lat"),
            func.ST_X(Vehicle.geom).label("lon")
        ).all()

        result = []

        for record in records:

            result.append({
                "id": record.vehicle_code,
                "driver": record.driver,
                "cargo": record.cargo,
                "lat": record.lat,
                "lon": record.lon,
                "speed": record.speed,
                "status": record.status
            })

        return {
            "timestamp": vehicle_data["timestamp"],
            "vehicles": result
        }

    except Exception as error:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )




# ============================================================
# WEATHER - POSTGRESQL INTEGRATION
# ============================================================

@app.get("/api/weather")
def weather(db: Session = Depends(get_db)):

    try:

        # Generate simulated weather data
        weather_data = get_weather()

        # Create a database record
        new_weather = Weather(
            rainfall=weather_data["rainfall_mm"],
            visibility=weather_data["visibility_km"],
            temperature=weather_data["temperature_c"],
            humidity=weather_data["humidity"],
            condition=weather_data["condition"],
            timestamp=datetime.now().astimezone()
        )

        # Save weather data in PostgreSQL
        db.add(new_weather)
        db.commit()
        db.refresh(new_weather)

        # Return the saved database record
        return {
            "rainfall_mm": new_weather.rainfall,
            "visibility_km": new_weather.visibility,
            "temperature_c": new_weather.temperature,
            "humidity": new_weather.humidity,
            "condition": new_weather.condition,
            "source": "SIMULATED",
            "timestamp": new_weather.timestamp.isoformat()
        }

    except Exception as error:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )




# ============================================================
# INCIDENTS - POSTGRESQL INTEGRATION
# ============================================================

@app.get("/api/incidents")
def incidents(db: Session = Depends(get_db)):

    records = db.query(Incident).all()

    result = []

    for incident in records:

        coordinates = None

        if incident.geom is not None:
            point = db.query(
                func.ST_X(Incident.geom),
                func.ST_Y(Incident.geom)
            ).filter(
                Incident.id == incident.id
            ).first()

            if point:
                coordinates = {
                    "lat": point[1],
                    "lon": point[0]
                }

        result.append({
            "id": incident.incident_code,
            "type": incident.type,
            "severity": incident.severity,
            "description": incident.description,
            "lat": coordinates["lat"] if coordinates else None,
            "lon": coordinates["lon"] if coordinates else None,
            "timestamp": (
                incident.timestamp.isoformat()
                if incident.timestamp else None
            ),
            "source": incident.source
        })

    return {"incidents": result}


@app.post("/api/incidents")
def create_incident(
    incident: IncidentCreate,
    db: Session = Depends(get_db)
):

    try:

        incident_count = db.query(Incident).count()

        new_incident = Incident(
            incident_code=f"INC-{incident_count + 1:03d}",
            type=incident.type,
            severity=incident.severity,
            description=incident.description,
            source="USER_REPORTED",
            timestamp=datetime.now().astimezone(),
            geom=(
                WKTElement(
                    f"POINT({incident.lon} {incident.lat})",
                    srid=4326
                )
                if incident.lat is not None
                and incident.lon is not None
                else None
            )
        )

        db.add(new_incident)
        db.commit()
        db.refresh(new_incident)

        return {
            "message": "Incident registered successfully",
            "incident": {
                "id": new_incident.incident_code,
                "type": new_incident.type,
                "severity": new_incident.severity,
                "description": new_incident.description,
                "lat": incident.lat,
                "lon": incident.lon,
                "timestamp": new_incident.timestamp.isoformat(),
                "source": new_incident.source
            }
        }

    except Exception as error:
        db.rollback()
        return {
            "error": str(error)
        }


@app.get("/api/risk")
def risk(db: Session = Depends(get_db)):

    # Fetch the latest weather record from the database
    latest_weather = (
        db.query(Weather)
        .order_by(Weather.timestamp.desc())
        .first()
    )

    # Use database values, or fallback values if no weather data exists
    features = {
        "rainfall": latest_weather.rainfall if latest_weather else 42.5,
        "visibility": latest_weather.visibility if latest_weather else 3.2,
        "traffic": 0.65,
        "slope": 0.72,
    }

    # Predict risk using the existing risk model
    prediction = predict_risk(features)

    # Calculate incident impact using database records
    incident_boost = 0

    incidents = db.query(Incident).all()

    for incident in incidents:
        if incident.severity.upper() == "HIGH":
            incident_boost += 20
        elif incident.severity.upper() == "MEDIUM":
            incident_boost += 10

    # Add incident impact to predicted risk score
    prediction["score"] = min(
        100,
        round(prediction["score"] + incident_boost, 2)
    )

    # Determine final risk level
    if prediction["score"] >= 70:
        prediction["level"] = "HIGH"
    elif prediction["score"] >= 40:
        prediction["level"] = "MEDIUM"
    else:
        prediction["level"] = "LOW"

    return {
        "features": features,
        "prediction": prediction,
        "incident_impact": incident_boost
    }


    # --------------------------------------------------------
    # INCIDENT IMPACT
    # --------------------------------------------------------

    incident_boost = 0

    for incident in db.query(Incident).all():

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
def routes(db: Session = Depends(get_db)):

    route_data = get_routes(db)

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

# @app.get("/api/network")
# def network():

#     network_file = (
#         Path(__file__).parent
#         / "data"
#         / "road_network.geojson"
#     )

#     with open(
#         network_file,
#         "r",
#         encoding="utf-8"
#     ) as file:

#         return json.load(file)

@app.get("/api/network")
def network(db: Session = Depends(get_db)):

    roads = db.query(
        Road.name,
        Road.risk,
        Road.route_type,
        func.ST_AsGeoJSON(Road.geom).label("geometry")
    ).all()

    features = []

    for road in roads:

        features.append({
            "type": "Feature",
            "properties": {
                "name": road.name,
                "risk": road.risk,
                "route_type": road.route_type
            },
            "geometry": json.loads(road.geometry)
        })

    return {
        "type": "FeatureCollection",
        "features": features
    }