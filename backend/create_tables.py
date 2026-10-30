from database import engine, Base
import models

# Create all database tables
Base.metadata.create_all(bind=engine)

print("Database tables created successfully!")