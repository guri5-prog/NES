import json
import logging
import hashlib
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import Depends, Request, Response
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_db
from models import Road, Incident, Vehicle, Weather, User, UserSession
from geoalchemy2 import WKTElement

from risk_model import predict_risk, calculate_segment_risk
from routing import get_routes, load_roads_dataset, haversine_distance, point_to_segment_distance_km
from live_sources import (
    get_unified_live_data,
    get_live_rainfall_openmeteo,
    get_live_weather_openweather,
    bbox_for_point,
    NE_STATE_BOUNDS,
    search_places,
    get_live_osm_route_roads,
    get_osrm_routes,
    get_route_weather_conditions,
    get_coolr_landslides,
    lhasa_image_url,
)


logger = logging.getLogger(__name__)

INCIDENT_PHOTO_DIR = Path(__file__).resolve().parent / "uploads" / "incidents"
INCIDENT_PHOTO_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_INCIDENT_PHOTO_BYTES = 8 * 1024 * 1024


def incident_photo_for_code(incident_code: Optional[str]):
    if not incident_code:
        return None
    for media_type, extension in INCIDENT_PHOTO_TYPES.items():
        path = INCIDENT_PHOTO_DIR / f"{incident_code}{extension}"
        if path.is_file():
            return path, media_type
    return None

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

DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:7357",
    "http://127.0.0.1:7357",
]
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
] or DEFAULT_CORS_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
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
            "photo_url": (
                f"/api/incidents/{incident.incident_code}/photo"
                if incident_photo_for_code(incident.incident_code) else None
            ),
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
                "source": new_incident.source,
                "photo_url": None,
            }
        }

    except SQLAlchemyError as error:
        db.rollback()
        logger.exception("Failed to persist incident")
        raise HTTPException(
            status_code=500,
            detail="Incident could not be saved.",
        ) from error


@app.post("/api/incidents/report", status_code=201)
async def create_incident_report_with_photo(
    request: Request,
    type: str,
    severity: str,
    description: str,
    lat: float,
    lon: float,
    db: Session = Depends(get_db),
    _user: User = Depends(authenticated_user),
):
    """Create an incident and store an attached image as an authenticated file."""
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    extension = INCIDENT_PHOTO_TYPES.get(media_type)
    if extension is None:
        raise HTTPException(status_code=415, detail="Upload a JPEG, PNG, or WebP photo.")

    try:
        report = IncidentCreate(type=type, severity=severity, description=description, lat=lat, lon=lon)
    except Exception as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_INCIDENT_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Photo must be 8 MB or smaller.")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_INCIDENT_PHOTO_BYTES:
            raise HTTPException(status_code=413, detail="Photo must be 8 MB or smaller.")
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded photo is empty.")
    valid_image = (
        (media_type == "image/jpeg" and content.startswith(b"\xff\xd8\xff"))
        or (media_type == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n"))
        or (media_type == "image/webp" and content[:4] == b"RIFF" and content[8:12] == b"WEBP")
    )
    if not valid_image:
        raise HTTPException(status_code=415, detail="The file contents do not match a JPEG, PNG, or WebP image.")

    incident_code = f"INC-{uuid4().hex.upper()}"
    photo_path = INCIDENT_PHOTO_DIR / f"{incident_code}{extension}"
    try:
        INCIDENT_PHOTO_DIR.mkdir(parents=True, exist_ok=True)
        photo_path.write_bytes(content)
        new_incident = Incident(
            incident_code=incident_code,
            type=report.type,
            severity=report.severity,
            description=report.description,
            source="USER_REPORTED",
            timestamp=datetime.now().astimezone(),
            geom=WKTElement(f"POINT({report.lon} {report.lat})", srid=4326),
        )
        db.add(new_incident)
        db.commit()
        db.refresh(new_incident)
        return {
            "message": "Incident and photo saved successfully.",
            "incident": {
                "id": new_incident.incident_code,
                "type": new_incident.type,
                "severity": new_incident.severity,
                "description": new_incident.description,
                "lat": report.lat,
                "lon": report.lon,
                "timestamp": new_incident.timestamp.isoformat(),
                "source": new_incident.source,
                "photo_url": f"/api/incidents/{new_incident.incident_code}/photo",
            },
        }
    except SQLAlchemyError as error:
        db.rollback()
        photo_path.unlink(missing_ok=True)
        logger.exception("Failed to persist incident report with photo")
        raise HTTPException(status_code=500, detail="Incident report could not be saved.") from error
    except OSError as error:
        db.rollback()
        photo_path.unlink(missing_ok=True)
        logger.exception("Failed to store incident photo")
        raise HTTPException(status_code=500, detail="Incident photo could not be stored.") from error


@app.get("/api/incidents/{incident_code}/photo")
def get_incident_photo(
    incident_code: str,
    db: Session = Depends(get_db),
    _user: User = Depends(authenticated_user),
):
    incident = db.query(Incident).filter(Incident.incident_code == incident_code).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")
    photo = incident_photo_for_code(incident.incident_code)
    if not photo:
        raise HTTPException(status_code=404, detail="This incident has no attached photo.")
    path, media_type = photo
    return FileResponse(path, media_type=media_type, filename=path.name, headers={"Cache-Control": "private, max-age=3600"})


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
    state: str = "Sikkim",
    origin_state: Optional[str] = None,
    destination_state: Optional[str] = None,
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
    origin_state = origin_state or state
    destination_state = destination_state or state
    if origin_state not in NE_STATE_BOUNDS or destination_state not in NE_STATE_BOUNDS:
        raise HTTPException(status_code=422, detail="Choose a Northeast state from the supported list.")
    if not (-180 <= start_lon <= 180 and -90 <= start_lat <= 90 and
            -180 <= destination_lon <= 180 and -90 <= destination_lat <= 90):
        raise HTTPException(status_code=422, detail="Route coordinates are outside valid latitude/longitude ranges.")

    def build_risk_sections(route_coordinates, segments):
        sections = []
        for position, segment in enumerate(segments):
            route_index = int(segment.get("route_index", position))
            if route_index < 0 or route_index + 1 >= len(route_coordinates):
                continue
            score = float(segment.get("risk_indicator") or 0.0)
            congestion_level = segment.get("congestion_level")
            band = ("congested_high" if congestion_level == "high" else "congested_mild") if segment.get("congestion_detected") else "elevated" if score >= 35 else "caution" if score >= 15 else "safe"
            section_coordinates = [route_coordinates[route_index], route_coordinates[route_index + 1]]
            previous = sections[-1] if sections else None
            if previous and previous["risk_band"] == band and previous["coordinates"][-1] == section_coordinates[0]:
                previous["coordinates"].append(section_coordinates[1])
                previous["max_risk_indicator"] = max(previous["max_risk_indicator"], score)
                previous["segment_count"] += 1
                previous["congestion_detected"] = previous["congestion_detected"] or bool(segment.get("congestion_detected"))
            else:
                sections.append({"risk_band": band, "coordinates": section_coordinates,
                    "max_risk_indicator": score, "segment_count": 1,
                    "congestion_detected": bool(segment.get("congestion_detected"))})
        return sections

    def is_congestion_report(incident):
        report_text = " ".join(str(incident.get(field) or "") for field in ("type", "description")).casefold()
        return any(term in report_text for term in ("congest", "traffic jam", "traffic queue", "road blockage", "road block", "blocked road", "closure"))

    def include_reported_congestion(assessment, incidents):
        reports = [incident for incident in incidents if is_congestion_report(incident)]
        if not reports:
            return assessment
        severity_floor = max(
            85.0 if str(report.get("severity", "")).upper() == "HIGH" else
            60.0 if str(report.get("severity", "")).upper() == "MEDIUM" else 45.0
            for report in reports
        )
        score = min(100.0, max(float(assessment["score"]), severity_floor + 5.0 * (len(reports) - 1)))
        assessment["score"] = round(score, 2)
        assessment["risk_level"] = "HIGH" if score >= 65 else "MEDIUM" if score >= 35 else "LOW"
        assessment["congestion_level"] = "high" if score >= 65 or any(str(report.get("severity", "")).upper() == "HIGH" for report in reports) else "mild"
        assessment["congestion_report_count"] = len(reports)
        assessment["risk_factors"] = list(dict.fromkeys([
            *assessment.get("risk_factors", []),
            f"Reported road congestion/blockage ({len(reports)} report{'s' if len(reports) != 1 else ''})",
        ]))
        return assessment

    def congestion_reports_near_segment(start_xy, end_xy, incident_points):
        return [incident for incident in incident_points
                if is_congestion_report(incident)
                and point_to_segment_distance_km(
                    (float(incident["lon"]), float(incident["lat"])), start_xy, end_xy) <= 0.75]

    origin_west, origin_south, origin_east, origin_north = NE_STATE_BOUNDS[origin_state]
    destination_west, destination_south, destination_east, destination_north = NE_STATE_BOUNDS[destination_state]
    if not (origin_west <= start_lon <= origin_east and origin_south <= start_lat <= origin_north):
        raise HTTPException(status_code=422, detail=f"The start location must be inside {origin_state}.")
    if not (destination_west <= destination_lon <= destination_east and
            destination_south <= destination_lat <= destination_north):
        raise HTTPException(status_code=422, detail=f"The destination must be inside {destination_state}.")

    margin = 0.12
    network_bbox = [min(start_lon, destination_lon)-margin, min(start_lat, destination_lat)-margin,
                    max(start_lon, destination_lon)+margin, max(start_lat, destination_lat)+margin]
    network_source = "checked-in Sikkim OSM road export"
    if origin_state != "Sikkim" or destination_state != "Sikkim":
        road_routes = get_osrm_routes([start_lon,start_lat],[destination_lon,destination_lat])
        if road_routes.get("status") != "LIVE_CONNECTED" or not road_routes.get("routes"):
            raise HTTPException(status_code=503, detail={"message":"The route service is temporarily unavailable. Try again shortly.",
                "source_status":road_routes.get("status")})
        options = road_routes["routes"]
        # Keep every returned path oriented from the selected origin to the
        # selected destination, even if an upstream routing provider returns
        # its GeoJSON coordinates in reverse order.
        requested_start = (start_lon, start_lat)
        requested_destination = (destination_lon, destination_lat)
        for option in options:
            route_coordinates = option.get("coordinates", [])
            if len(route_coordinates) < 2:
                continue
            forward_gap = (haversine_distance(requested_start, route_coordinates[0])
                           + haversine_distance(requested_destination, route_coordinates[-1]))
            reverse_gap = (haversine_distance(requested_start, route_coordinates[-1])
                           + haversine_distance(requested_destination, route_coordinates[0]))
            if reverse_gap < forward_gap:
                option["coordinates"] = list(reversed(route_coordinates))
        primary = options[0]
        alternate = options[1] if len(options) > 1 else {**primary, "coordinates": [], "distance_km": None, "duration_minutes": None}
        primary["route_type"] = "primary"
        alternate["route_type"] = "alternative"
        with ThreadPoolExecutor(max_workers=2) as pool:
            weather_jobs = {
                "normal": pool.submit(get_route_weather_conditions, primary["coordinates"]),
                "safer": pool.submit(get_route_weather_conditions, alternate["coordinates"]),
            }
            route_weather = {key: job.result() for key, job in weather_jobs.items()}

        incident_records = db.query(
            Incident,
            func.ST_Y(Incident.geom).label("lat"),
            func.ST_X(Incident.geom).label("lon"),
        ).all()
        incident_points = [
            {"id": incident.incident_code or incident.id, "severity": incident.severity,
             "type": incident.type, "description": incident.description, "lat": lat, "lon": lon}
            for incident, lat, lon in incident_records if lat is not None and lon is not None
        ]

        def assess_external_route(route, conditions):
            coordinates = route.get("coordinates", [])
            weather_points = [point for point in conditions.get("points", [])
                              if point.get("rainfall_mm") is not None or point.get("rainfall_24h_mm") is not None
                              or point.get("visibility_km") is not None]
            has_weather_observation = bool(weather_points)
            segment_results = []
            seen_incidents = set()
            all_factors = []
            total_length = 0.0
            weighted_score = 0.0

            for index, (start_point, end_point) in enumerate(zip(coordinates[:-1], coordinates[1:]), start=1):
                start_xy = (float(start_point[0]), float(start_point[1]))
                end_xy = (float(end_point[0]), float(end_point[1]))
                segment_length = haversine_distance(start_xy, end_xy)
                if segment_length <= 0:
                    continue
                midpoint = ((start_xy[0] + end_xy[0]) / 2.0, (start_xy[1] + end_xy[1]) / 2.0)
                local_incidents = [incident for incident in incident_points
                    if point_to_segment_distance_km(
                        (float(incident["lon"]), float(incident["lat"])), start_xy, end_xy) <= 2.0]
                local_congestion = congestion_reports_near_segment(start_xy, end_xy, incident_points)
                if weather_points:
                    weather_point = min(weather_points, key=lambda point: haversine_distance(
                        midpoint, (float(point["lon"]), float(point["lat"]))))
                    rainfall = weather_point.get("rainfall_mm")
                    rainfall_24h = weather_point.get("rainfall_24h_mm")
                    visibility = weather_point.get("visibility_km")
                else:
                    rainfall, rainfall_24h, visibility = None, None, None
                assessment = calculate_segment_risk(
                    segment_id=f"route-segment-{index}", base_risk=0.0,
                    rainfall_mm=float(rainfall or 0.0),
                    rainfall_24h_mm=rainfall_24h,
                    visibility_km=float(visibility if visibility is not None else 10.0),
                    slope_deg=0.0, active_incidents=local_incidents)
                assessment = include_reported_congestion(assessment, local_congestion)
                score = float(assessment["score"])
                total_length += segment_length
                weighted_score += score * segment_length
                all_factors.extend(assessment["risk_factors"])
                seen_incidents.update(incident["id"] for incident in local_incidents)
                segment_results.append({
                    "segment_id": assessment["segment_id"],
                    "route_index": index - 1,
                    "distance_km": round(segment_length, 2),
                    "risk_indicator": score,
                    "risk_level": assessment["risk_level"],
                    "risk_factors": assessment["risk_factors"],
                    "nearby_incident_count": len(local_incidents),
                    "congestion_detected": bool(local_congestion),
                    "congestion_level": assessment.get("congestion_level"),
                    "congestion_report_count": assessment.get("congestion_report_count", 0),
                })

            if not total_length or (not has_weather_observation and not seen_incidents):
                route.update({"risk_score": None, "risk_probability": None, "risk_indicator": None,
                    "risk_level": "UNKNOWN", "risk_factors": [], "risk_assessment_type": "heuristic",
                    "risk_data_status": "INSUFFICIENT_DATA"})
                return

            route_score = round(weighted_score / total_length, 2)
            risk_level = "HIGH" if route_score >= 65 else "MEDIUM" if route_score >= 35 else "LOW"
            factors = [factor for factor in dict.fromkeys(all_factors)
                       if factor != "Nominal Mountain Corridor Baseline"] or ["Nominal Mountain Corridor Baseline"]
            risk_sections = build_risk_sections(coordinates, segment_results)
            segment_results.sort(key=lambda item: item["risk_indicator"], reverse=True)
            route.update({"risk_score": route_score, "risk_probability": None,
                "risk_indicator": route_score, "risk_level": risk_level,
                "risk_factors": factors, "risk_assessment_type": "heuristic",
                "risk_data_status": "LIVE_DATA" if has_weather_observation else "INCIDENTS_ONLY",
                "nearby_incident_count": len(seen_incidents), "segments": segment_results[:5],
                "risk_sections": risk_sections})

        assess_external_route(primary, route_weather["normal"])
        if len(options) > 1:
            assess_external_route(alternate, route_weather["safer"])
        lines = [route["coordinates"] for route in options]
        return {
            "normal": primary,
            "safer": alternate,
            "has_alternative": len(options) > 1,
            "route_conditions": route_weather,
            "area": {"state":f"{origin_state} → {destination_state}","network_source":road_routes.get("provider", "OpenStreetMap directions"),"bbox":network_bbox},
            "network": {"type":"FeatureCollection","features":[
                {"type":"Feature","properties":{"name":"Route option","route_index":index},
                 "geometry":{"type":"LineString","coordinates":coordinates}}
                for index,coordinates in enumerate(lines)]},
        }

    corridor_coordinates = [[start_lon, start_lat],
        [(start_lon + destination_lon) / 2, (start_lat + destination_lat) / 2],
        [destination_lon, destination_lat]]
    corridor_conditions = get_route_weather_conditions(corridor_coordinates)
    corridor_summary = corridor_conditions.get("summary", {})
    route_weather_context = {
        "rainfall_mm": corridor_summary.get("maximum_rainfall_mm") or 0.0,
        "rainfall_24h_mm": corridor_summary.get("maximum_rainfall_24h_mm"),
        "visibility_km": corridor_summary.get("minimum_visibility_km")
            if corridor_summary.get("minimum_visibility_km") is not None else 10.0,
    }
    result = get_routes(db, alpha=alpha, beta=beta,
                        start=[start_lon, start_lat], destination=[destination_lon, destination_lat],
                        weather_context=route_weather_context)
    with ThreadPoolExecutor(max_workers=2) as pool:
        weather_jobs = {
            "normal": pool.submit(get_route_weather_conditions, (result.get("normal") or {}).get("coordinates", [])),
            "safer": pool.submit(get_route_weather_conditions, (result.get("safer") or {}).get("coordinates", [])),
        }
        result["route_conditions"] = {key: job.result() for key, job in weather_jobs.items()}

    # Re-score each selected Sikkim path with its own route weather samples and
    # incident-to-road proximity instead of reusing the straight-corridor max.
    incident_records = db.query(
        Incident,
        func.ST_Y(Incident.geom).label("lat"),
        func.ST_X(Incident.geom).label("lon"),
    ).filter(Incident.geom.isnot(None)).all()
    incident_points = [
        {"id": incident.incident_code or incident.id, "severity": incident.severity,
         "type": incident.type, "description": incident.description, "lat": lat, "lon": lon}
        for incident, lat, lon in incident_records if lat is not None and lon is not None
        and 87.0 <= lon <= 90.0 and 26.0 <= lat <= 29.0
    ]
    for route_key in ("normal", "safer"):
        route = result.get(route_key) or {}
        coordinates = route.get("coordinates", [])
        conditions = result["route_conditions"].get(route_key, {})
        weather_points = [point for point in conditions.get("points", [])
                          if point.get("rainfall_mm") is not None or point.get("rainfall_24h_mm") is not None
                          or point.get("visibility_km") is not None]
        segments = route.get("segments", [])
        total_length = weighted_score = 0.0
        all_factors = []
        seen_incidents = set()
        for index, (start_point, end_point) in enumerate(zip(coordinates[:-1], coordinates[1:])):
            if index >= len(segments):
                break
            start_xy, end_xy = tuple(start_point), tuple(end_point)
            segment = segments[index]
            local_incidents = [incident for incident in incident_points
                if point_to_segment_distance_km(
                    (float(incident["lon"]), float(incident["lat"])), start_xy, end_xy) <= 2.0]
            local_congestion = congestion_reports_near_segment(start_xy, end_xy, incident_points)
            midpoint = ((start_xy[0] + end_xy[0]) / 2.0, (start_xy[1] + end_xy[1]) / 2.0)
            weather_point = min(weather_points, key=lambda point: haversine_distance(
                midpoint, (float(point["lon"]), float(point["lat"])))) if weather_points else {}
            assessment = calculate_segment_risk(
                segment_id=segment["segment_id"], base_risk=float(segment.get("base_risk") or 0.0),
                rainfall_mm=float(weather_point.get("rainfall_mm") or 0.0),
                rainfall_24h_mm=weather_point.get("rainfall_24h_mm"),
                visibility_km=float(weather_point.get("visibility_km")
                                    if weather_point.get("visibility_km") is not None else 10.0),
                slope_deg=0.0, active_incidents=local_incidents)
            assessment = include_reported_congestion(assessment, local_congestion)
            segment_length = float(segment.get("distance_km") or 0.0)
            segment["risk_indicator"] = assessment["score"]
            segment["risk_level"] = assessment["risk_level"]
            segment["risk_factors"] = assessment["risk_factors"]
            segment["nearby_incident_count"] = len(local_incidents)
            segment["congestion_detected"] = bool(local_congestion)
            segment["congestion_level"] = assessment.get("congestion_level")
            segment["congestion_report_count"] = assessment.get("congestion_report_count", 0)
            segment["risk_probability"] = None
            total_length += segment_length
            weighted_score += assessment["score"] * segment_length
            all_factors.extend(assessment["risk_factors"])
            seen_incidents.update(incident["id"] for incident in local_incidents)
        if total_length:
            route_score = round(weighted_score / total_length, 2)
            route["risk_score"] = route["risk_indicator"] = route_score
            route["risk_probability"] = None
            route["risk_level"] = "HIGH" if route_score >= 65 else "MEDIUM" if route_score >= 35 else "LOW"
            route["risk_factors"] = [factor for factor in dict.fromkeys(all_factors)
                                     if factor != "Nominal Mountain Corridor Baseline"] or ["Nominal Mountain Corridor Baseline"]
            route["risk_assessment_type"] = "heuristic"
            route["risk_data_status"] = "LIVE_DATA" if weather_points else ("INCIDENTS_ONLY" if seen_incidents else "STATIC_BASELINE")
            route["nearby_incident_count"] = len(seen_incidents)
            route["risk_sections"] = build_risk_sections(coordinates, segments)
    result["route_weather_context_used"] = route_weather_context
    result["has_alternative"] = bool(result.get("safer", {}).get("coordinates") and
                                     result.get("safer", {}).get("coordinates") != result.get("normal", {}).get("coordinates"))
    result["area"] = {"state":f"{origin_state} → {destination_state}","network_source":network_source,"bbox":network_bbox}
    return result


@app.get("/api/places/search")
def place_search(
    q: str,
    state: str,
    _user: User = Depends(authenticated_user),
):
    """Explicit place search bounded to a selected Northeast state."""
    try:
        return search_places(q, state)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/landslides")
def landslide_layers(
    west: float,
    south: float,
    east: float,
    north: float,
    days: int = 7,
    _user: User = Depends(authenticated_user),
):
    """On-demand NASA COOLR events plus an independently toggleable LHASA nowcast."""
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise HTTPException(status_code=422, detail="Invalid map bounds for landslide query.")
    if not 1 <= days <= 30:
        raise HTTPException(status_code=422, detail="History duration must be between 1 and 30 days.")
    if east - west > 15 or north - south > 12:
        raise HTTPException(status_code=422, detail="Zoom in to a route or smaller area before loading landslides.")
    result = get_coolr_landslides(west, south, east, north, days)
    result["lhasa"] = {
        "status": "AVAILABLE",
        "image_url": lhasa_image_url(west, south, east, north),
        "bounds": [[south, west], [north, east]],
        "source": "NASA LHASA current hazard nowcast (roughly 1 km; updates several times daily)",
    }
    return result


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
    state: str = "Sikkim",
    west: float = 88.20,
    south: float = 27.00,
    east: float = 88.90,
    north: float = 27.65,
    _user: User = Depends(authenticated_user),
):
    if state not in NE_STATE_BOUNDS:
        raise HTTPException(status_code=422, detail="Choose a Northeast state from the supported list.")
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise HTTPException(status_code=422, detail="Invalid network bounding box.")
    if state != "Sikkim":
        data = get_live_osm_route_roads([west, south, east, north])
        if data.get("status") != "LIVE_CONNECTED":
            raise HTTPException(status_code=503, detail="Live OpenStreetMap road network is unavailable for this area.")
        return {"type":"FeatureCollection", "features":[{"type":"Feature", "properties":{
            "name":road.get("name"),"route_type":road.get("route_type"),"osm_id":road.get("id")},
            "geometry":road.get("geometry")} for road in data.get("roads",[])]}
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
