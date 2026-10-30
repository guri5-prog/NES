import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker, declarative_base

# Load environment variables explicitly from backend/.env, falling back to root
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)
load_dotenv()

# Database configuration
DATABASE_URL = URL.create(
    drivername="postgresql+psycopg2",
    username=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", 5432)),
    database=os.getenv("DB_NAME"),
)

# Create database engine with connection timeout to prevent indefinite hangs
engine = create_engine(
    DATABASE_URL,
    echo=True,
    connect_args={"connect_timeout": 5}
)

# Create database sessions
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Base class for database models
Base = declarative_base()


# Database dependency for FastAPI
def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


# Test database connection
if __name__ == "__main__":
    try:
        with engine.connect() as connection:
            result = connection.execute(
                text("SELECT PostGIS_Full_Version();")
            )

            print("Database connected successfully!")
            print(result.scalar())

    except Exception as error:
        print("Database connection failed!")
        print(error)
