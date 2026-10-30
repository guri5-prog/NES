
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Text
)

from geoalchemy2 import Geometry
from database import Base

from sqlalchemy import ForeignKey
from sqlalchemy.orm import relationship

from sqlalchemy import func



# =========================================
# ROADS TABLE
# =========================================

class Road(Base):
    __tablename__ = "roads"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(150), nullable=False)

    risk = Column(Float, default=0)

    route_type = Column(String(50))

    geom = Column(
        Geometry(
            geometry_type="LINESTRING",
            srid=4326,
            spatial_index=True
        )
    )


# =========================================
# INCIDENTS TABLE
# =========================================

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)

    incident_code = Column(String(50), unique=True)

    type = Column(String(100))

    severity = Column(String(50))

    description = Column(Text)

    source = Column(String(50))

    timestamp = Column(DateTime(timezone=True))

    geom = Column(
        Geometry(
            geometry_type="POINT",
            srid=4326,
            spatial_index=True
        )
    )


# =========================================
# VEHICLES TABLE
# =========================================

class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)

    vehicle_code = Column(String(50), unique=True)

    driver = Column(String(100))

    cargo = Column(String(150))

    speed = Column(Float)

    status = Column(String(50))

    geom = Column(
        Geometry(
            geometry_type="POINT",
            srid=4326,
            spatial_index=True
        )
    )


# =========================================
# WEATHER TABLE
# =========================================

class Weather(Base):
    __tablename__ = "weather"

    id = Column(Integer, primary_key=True, index=True)

    rainfall = Column(Float)

    visibility = Column(Float)

    temperature = Column(Float)

    humidity = Column(Float)

    condition = Column(String(100))

    timestamp = Column(DateTime(timezone=True))

# =========================================
# USER MODEL
# =========================================


class User(Base):

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(100), nullable=False)

    email = Column(String(150), unique=True, nullable=False, index=True)

    password_hash = Column(Text, nullable=False)

    role = Column(String(30), default="USER")

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    sessions = relationship(
        "UserSession",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    # =========================================
# USER SESSION MODEL
# =========================================

class UserSession(Base):

    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )

    token_hash = Column(Text, unique=True, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    expires_at = Column(DateTime(timezone=True), nullable=False)

    revoked_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="sessions")