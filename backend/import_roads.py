import json
from pathlib import Path

from geoalchemy2 import WKTElement
from database import SessionLocal
from models import Road

GEOJSON_PATH = (
    Path(__file__).parent
    / "data"
    / "road_network.geojson"
)


def import_roads():
    db = SessionLocal()

    try:
        with open(GEOJSON_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)

        count = 0

        for feature in data["features"]:
            properties = feature["properties"]
            geometry = feature["geometry"]

            if geometry["type"] != "LineString":
                continue

            name = properties.get("name", "Unnamed Road")
            risk = float(properties.get("risk", 0))
            route_type = properties.get("route_type", "alternate")

            coordinates = geometry["coordinates"]

            coordinate_text = ", ".join(
                f"{lon} {lat}" for lon, lat in coordinates
            )

            wkt = f"LINESTRING ({coordinate_text})"

            road = db.query(Road).filter_by(name=name).first()

            if road is None:
                road = Road(name=name)
                db.add(road)

            road.risk = risk
            road.route_type = route_type
            road.geom = WKTElement(wkt, srid=4326)

            count += 1

        db.commit()
        print(f"Successfully imported {count} roads!")

    except Exception as e:
        db.rollback()
        print("Error importing roads:", e)

    finally:
        db.close()


if __name__ == "__main__":
    import_roads()