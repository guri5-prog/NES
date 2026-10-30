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

from risk_model import predict_risk, calculate_segment_risk
from routing import get_routes, load_roads_dataset
from live_sources import (
    get_unified_live_data,
    get_live_rainfall_openmeteo,
    get_live_weather_openweather,
    bbox_for_point,
)


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
        "docs": "/docs",
        "redoc": "/redoc",
        "status": "OK"
    }


@app.get("/api")
def api_root():
    return {
        "message": "AI Smart Logistics API is running",
        "docs": "/docs",
        "redoc": "/redoc",
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

        # Return only persisted fleet telemetry; do not fabricate vehicle locations.
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
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "vehicles": result
        }

    except HTTPException:
        db.rollback()
        raise
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
        live_meteo = get_live_rainfall_openmeteo(lat=27.33, lon=88.61)
        if live_meteo.get("status") != "LIVE_CONNECTED":
            return {"status":live_meteo.get("status"),"source":"Open-Meteo","rainfall_mm":None,
                    "visibility_km":None,"temperature_c":None,"humidity":None,
                    "timestamp":live_meteo.get("timestamp"),"message":"No current weather observation is available."}
        rainfall = live_meteo.get("rainfall_mm")
        temp = live_meteo.get("temperature_c")
        humidity = live_meteo.get("humidity")
        live_weather = get_live_weather_openweather(lat=27.33, lon=88.61)
        visibility = live_weather.get("visibility_km") if live_weather.get("status") == "LIVE_CONNECTED" else None
        condition = live_weather.get("condition") or ("Rain" if (rainfall or 0) > 0 else "No precipitation reported")

        # Create a database record
        new_weather = Weather(
            rainfall=rainfall,
            visibility=visibility,
            temperature=temp,
            humidity=humidity,
            condition=condition,
            timestamp=datetime.now().astimezone()
        )

        # Save weather data in PostgreSQL
        db.add(new_weather)
        db.commit()
        db.refresh(new_weather)

        return {
            "status": "LIVE_CONNECTED",
            "rainfall_mm": new_weather.rainfall,
            "visibility_km": new_weather.visibility,
            "temperature_c": new_weather.temperature,
            "humidity": new_weather.humidity,
            "condition": new_weather.condition,
            "source": "Open-Meteo",
            "visibility_source": live_weather.get("source") if visibility is not None else None,
            "openweather_status": live_weather.get("status"),
            "timestamp": new_weather.timestamp.isoformat()
        }

    except HTTPException:
        db.rollback()
        raise
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

    # Avoid silently presenting demo weather values as current observations.
    features = {
        "rainfall": latest_weather.rainfall if latest_weather and latest_weather.rainfall is not None else 0.0,
        "visibility": latest_weather.visibility if latest_weather and latest_weather.visibility is not None else 10.0,
        "traffic": 0.0,
        "slope": 0.0,
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
        "incident_impact": incident_boost,
        "output_type": "HEURISTIC_DISRUPTION_INDICATOR_NOT_CALIBRATED_PROBABILITY",
    }


# ============================================================
# ROUTES
# ============================================================

@app.get("/api/routes")
def routes(
    alpha: float = 1.0,
    beta: float = 25.0,
    start_lon: float = 88.6138,
    start_lat: float = 27.3389,
    destination_lon: float = 88.3639,
    destination_lat: float = 27.1667,
    db: Session = Depends(get_db),
    _user: User = Depends(authenticated_user),
):
    """
    Computes routes using the configured distance plus heuristic risk-index cost:
        C(e) = alpha * D(e) + beta * R(e)
    Where:
        - alpha: Weight assigned to distance D(e) in km (default: 1.0)
        - beta: Weight assigned to normalized heuristic indicator R(e) in [0, 1] (default: 25.0)
    """
    if not (-180 <= start_lon <= 180 and -90 <= start_lat <= 90 and
            -180 <= destination_lon <= 180 and -90 <= destination_lat <= 90):
        raise HTTPException(status_code=422, detail="Route coordinates are outside valid latitude/longitude ranges.")
    return get_routes(db, alpha=alpha, beta=beta,
                      start=[start_lon, start_lat],
                      destination=[destination_lon, destination_lat])


@app.get("/api/risk/segments")
def risk_segments(
    db: Session = Depends(get_db),
    _user: User = Depends(authenticated_user),
):
    """
    Returns heuristic dynamic disruption indicators for Sikkim OSM road records.
    These are not trained model probabilities; use /api/susceptibility/predict for
    the separate terrain susceptibility model output.
    - segment_id: Unique segment identifier
    - risk_probability: null; this backend has no calibrated disruption probability model
    - risk_level: LOW, MEDIUM, or HIGH
    - risk_factors: Key driving hazard features
    """
    roads = load_roads_dataset()
    latest_weather = db.query(Weather).order_by(Weather.timestamp.desc()).first()
    rainfall = latest_weather.rainfall if latest_weather and latest_weather.rainfall is not None else 0.0
    visibility = latest_weather.visibility if latest_weather and latest_weather.visibility is not None else 10.0

    incidents_db = db.query(Incident).filter(Incident.geom.isnot(None)).all()
    incidents = [{"severity": inc.severity, "type": inc.type} for inc in incidents_db]

    segments = []
    for road in roads:
        seg_id = f"OSM-{road.get('id')}"
        info = calculate_segment_risk(
            segment_id=seg_id,
            base_risk=float(road.get("risk") or 0.0),
            rainfall_mm=rainfall,
            visibility_km=visibility,
            slope_deg=0.0,
        )
        info["road_name"] = road.get("name")
        info["route_type"] = road.get("route_type")
        info["risk_type"] = "HEURISTIC_DISRUPTION_INDICATOR_NOT_CALIBRATED_PROBABILITY"
        info["disruption_probability"] = None
        info["risk_indicator"] = info.pop("score", None)
        info["risk_probability"] = None
        segments.append(info)

    return {
        "total_segments": len(segments),
        "environmental_context": {
            "rainfall_mm": rainfall,
            "visibility_km": visibility,
            "active_incidents": len(incidents),
        },
        "segments": segments,
    }


@app.get("/api/live-sources")
def live_sources(
    lat: float = 27.5,
    lon: float = 88.5,
    radius_degrees: float = 0.65,
    _user: User = Depends(authenticated_user),
):
    """
    Aggregated live feeds from 8 key satellite, meteorological and hazard sources:
    Open-Meteo, OpenWeather, NASA EONET, NASA FIRMS, OpenTopography,
    OpenStreetMap, ISRO MOSDAC, Copernicus GloFAS, and Mapillary.
    """
    if not -90 <= lat <= 90 or not -180 <= lon <= 180 or not 0.01 <= radius_degrees <= 2:
        raise HTTPException(status_code=422, detail="Invalid coordinates or radius_degrees (0.01 to 2).")
    return get_unified_live_data(lat=lat, lon=lon, bbox=bbox_for_point(lat, lon, radius_degrees))


class SusceptibilityInput(BaseModel):
    features: dict[str, float]
    segment_id: Optional[str] = Field(default=None, max_length=100)


@app.post("/api/susceptibility/predict")
def susceptibility_predict(
    payload: SusceptibilityInput,
    _user: User = Depends(authenticated_user),
):
    """Score one point with the trained Sikkim landslide initiation model.

    This estimates terrain susceptibility, not a live road closure/disruption probability.
    Supply all feature columns from model/models/feature_schema_v3.json.
    """
    from risk_model import predict_landslide_susceptibility
    try:
        return predict_landslide_susceptibility(payload.features, segment_id=payload.segment_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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
def network(
    west: float = 88.20,
    south: float = 27.00,
    east: float = 88.90,
    north: float = 27.65,
    _user: User = Depends(authenticated_user),
):
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise HTTPException(status_code=422, detail="Invalid network bounding box.")
    features = []
    for road in load_roads_dataset():
        try:
            geometry = json.loads(road["geometry"])
        except (KeyError, TypeError, ValueError):
            continue
        coordinates = geometry.get("coordinates", [])
        if not any(west <= point[0] <= east and south <= point[1] <= north for point in coordinates if len(point) >= 2):
            continue
        features.append({"type":"Feature", "properties":{
            "name":road.get("name"),"risk":road.get("risk"),"route_type":road.get("route_type"),"osm_id":road.get("id")},
            "geometry":geometry})

    return {
        "type": "FeatureCollection",
        "features": features
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
