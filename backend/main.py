import json
import logging
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from fastapi import Depends, Request, Response
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_db
from models import Road, Incident, Vehicle, Weather, User, UserSession
from geoalchemy2 import WKTElement

from data_gen import (
    get_vehicles,
    get_weather,
)

from risk_model import predict_risk
from routing import get_routes


logger = logging.getLogger(__name__)

SESSION_COOKIE = "nes_session"
SESSION_TTL = timedelta(days=14)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt_hex, expected_hex = stored_hash.split("$", 2)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1
        )
        return secrets.compare_digest(actual.hex(), expected_hex)
    except (ValueError, TypeError):
        return False


def public_user(user: User) -> dict:
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role}


def issue_session(user: User, response: Response, db: Session) -> None:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + SESSION_TTL
    db.add(UserSession(
        user_id=user.id,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        expires_at=expires_at,
    ))
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        samesite="lax",
        max_age=int(SESSION_TTL.total_seconds()),
        path="/",
    )


def find_session_user(request: Request, db: Session) -> Optional[User]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    session = db.query(UserSession).filter(
        UserSession.token_hash == token_hash,
        UserSession.revoked_at.is_(None),
        UserSession.expires_at > datetime.now(timezone.utc),
    ).first()
    return session.user if session else None


def authenticated_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = find_session_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    return user


class AuthInput(BaseModel):
    email: str = Field(min_length=3, max_length=150)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value:
            raise ValueError("Enter a valid email address.")
        return value


class RegisterInput(AuthInput):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return value


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
# INCIDENT MODEL
# ============================================================

class IncidentCreate(BaseModel):
    type: str = Field(min_length=1, max_length=100)
    severity: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1)
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lon: Optional[float] = Field(default=None, ge=-180, le=180)

    @field_validator("type", "severity", "description")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field must not be blank.")
        return value

    @model_validator(mode="after")
    def require_coordinate_pair(self):
        if (self.lat is None) != (self.lon is None):
            raise ValueError("Latitude and longitude must be provided together.")
        return self


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():
    return {
        "message": "AI Smart Logistics API is running",
        "status": "OK"
    }


@app.post("/api/auth/register", status_code=201)
def register(payload: RegisterInput, response: Response, db: Session = Depends(get_db)):
    email = payload.email
    if db.query(User.id).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(name=payload.name, email=email, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.flush()
        issue_session(user, response, db)
        db.commit()
        db.refresh(user)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from error
    return {"user": public_user(user)}


@app.post("/api/auth/login")
def login(payload: AuthInput, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(func.lower(User.email) == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    issue_session(user, response, db)
    db.commit()
    return {"user": public_user(user)}


@app.get("/api/auth/session")
def auth_session(request: Request, db: Session = Depends(get_db)):
    user = find_session_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return {"user": public_user(user)}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        session = db.query(UserSession).filter(
            UserSession.token_hash == token_hash,
            UserSession.revoked_at.is_(None),
        ).first()
        if session:
            session.revoked_at = datetime.now(timezone.utc)
            db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
    return {"message": "Signed out."}



# ============================================================
# VEHICLES - POSTGRESQL INTEGRATION
# ============================================================

@app.get("/api/vehicles")
def vehicles(db: Session = Depends(get_db), _user: User = Depends(authenticated_user)):

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
def weather(db: Session = Depends(get_db), _user: User = Depends(authenticated_user)):

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
def incidents(db: Session = Depends(get_db), _user: User = Depends(authenticated_user)):

    records = db.query(
        Incident,
        func.ST_Y(Incident.geom).label("lat"),
        func.ST_X(Incident.geom).label("lon"),
    ).order_by(
        Incident.timestamp.desc(),
        Incident.id.desc(),
    ).all()

    result = [
        {
            "id": incident.incident_code or f"INC-{incident.id:03d}",
            "type": incident.type,
            "severity": incident.severity,
            "description": incident.description,
            "lat": lat,
            "lon": lon,
            "timestamp": (
                incident.timestamp.isoformat()
                if incident.timestamp else None
            ),
            "source": incident.source,
        }
        for incident, lat, lon in records
    ]

    return {"incidents": result}


@app.post("/api/incidents")
def create_incident(
    incident: IncidentCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(authenticated_user),
):

    try:

        new_incident = Incident(
            incident_code=f"INC-{uuid4().hex.upper()}",
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

    except SQLAlchemyError as error:
        db.rollback()
        logger.exception("Failed to persist incident")
        raise HTTPException(
            status_code=500,
            detail="Incident could not be saved.",
        ) from error


@app.get("/api/risk")
def risk(db: Session = Depends(get_db), _user: User = Depends(authenticated_user)):

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
        severity = (incident.severity or "").upper()
        if severity == "HIGH":
            incident_boost += 20
        elif severity == "MEDIUM":
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


# ============================================================
# ROUTES
# ============================================================

@app.get("/api/routes")
def routes(db: Session = Depends(get_db), _user: User = Depends(authenticated_user)):

    route_data = get_routes(db)

    primary_risk = route_data["normal"]["risk_score"]

    # --------------------------------------------------------
    # If a high-severity incident is reported,
    # increase the primary route risk.
    # --------------------------------------------------------

    high_severity_incident = db.query(Incident.id).filter(
        func.upper(Incident.severity) == "HIGH"
    ).first()

    if high_severity_incident:
        primary_risk = min(100, primary_risk + 13)


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
def network(db: Session = Depends(get_db), _user: User = Depends(authenticated_user)):

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
