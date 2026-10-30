"""Live source adapters. Unavailable feeds return null data, never demo values."""

import csv
from concurrent.futures import ThreadPoolExecutor
import io
import logging
import math
import os
import time
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
_CACHE: Dict[str, tuple] = {}
CACHE_TTL_SECONDS = 900
USER_AGENT = "SETU-NER/1.0 (road risk research; contact project maintainers)"
NE_STATE_BOUNDS = {
    "Northeast India": [87.7, 21.8, 97.5, 29.6],
    "Arunachal Pradesh": [91.4, 26.5, 97.5, 29.6],
    "Assam": [89.5, 24.0, 96.2, 28.3],
    "Manipur": [93.0, 23.8, 94.9, 25.8],
    "Meghalaya": [89.7, 25.0, 92.8, 26.2],
    "Mizoram": [92.1, 21.8, 93.5, 24.6],
    "Nagaland": [93.3, 25.2, 95.4, 27.1],
    "Sikkim": [87.7, 27.0, 89.2, 28.2],
    "Tripura": [91.0, 22.9, 92.3, 24.5],
}
_GEOCODE_CACHE: Dict[str, list] = {}
_GEOCODE_LOCK = threading.Lock()
_LAST_GEOCODE_AT = 0.0
_OSRM_LOCK = threading.Lock()
_LAST_OSRM_AT = 0.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 10.0) -> Optional[bytes]:
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=req_headers), timeout=timeout) as response:
            return response.read() if response.status == 200 else None
    except Exception as exc:
        logger.info("External feed unavailable (%s): %s", urllib.parse.urlsplit(url).hostname, exc)
        return None


def _json(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 10.0) -> Optional[dict]:
    import json
    body = _fetch(url, headers, timeout=timeout)
    if body is None:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def _cached(key: str, loader, cache_failures: bool = True):
    now = time.time()
    entry = _CACHE.get(key)
    if entry and now - entry[0] < (CACHE_TTL_SECONDS if entry[1].get("status") == "LIVE_CONNECTED" else 60):
        value = dict(entry[1])
        value["cache"] = "HIT"
        return value
    value = loader()
    value.setdefault("timestamp", _now())
    value["cache"] = "MISS"
    if cache_failures or value.get("status") == "LIVE_CONNECTED":
        _CACHE[key] = (now, dict(value))
    return value


NASA_COOLR_LAYERS = {
    "points": "https://gis.earthdata.nasa.gov/portal/rest/services/Landslides/COOLR_Reports_Points/FeatureServer/0/query",
    "polygons": "https://gis.earthdata.nasa.gov/portal/rest/services/Landslides/COOLR_Events_Polygons/FeatureServer/0/query",
}
NASA_LHASA_TODAY = "https://gis.earthdata.nasa.gov/portal/rest/services/Landslides/LHASA_Hazard_Today/ImageServer"


def get_coolr_landslides(west: float, south: float, east: float, north: float, days: int = 7) -> Dict[str, Any]:
    """Fetch recent NASA COOLR reports and mapped event polygons for a map extent."""
    west, south, east, north = (round(float(value), 3) for value in (west, south, east, north))
    days = max(1, min(int(days), 30))
    cache_key = f"nasa-coolr:{west}:{south}:{east}:{north}:{days}"

    def load():
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_sql = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        bbox = f"{west},{south},{east},{north}"
        def query_layer(layer, endpoint):
            features = []
            offset = 0
            try:
                while offset < 6000:
                    params = urllib.parse.urlencode({
                        "where": f"event_date >= TIMESTAMP '{cutoff_sql}'",
                        "geometry": bbox,
                        "geometryType": "esriGeometryEnvelope",
                        "spatialRel": "esriSpatialRelIntersects",
                        "inSR": "4326", "outSR": "4326", "outFields": "*",
                        "returnGeometry": "true", "f": "geojson",
                        "orderByFields": "event_date DESC",
                        "resultRecordCount": 2000, "resultOffset": offset,
                    })
                    result = _json(endpoint + "?" + params, timeout=12.0)
                    if not result or result.get("error"):
                        logger.info("NASA COOLR %s query returned no usable response", layer)
                        return layer, {"type": "FeatureCollection", "features": features}, "UNAVAILABLE"
                    page = result.get("features") or []
                    features.extend(page)
                    offset += len(page)
                    if len(page) < 2000 or result.get("exceededTransferLimit") is False:
                        break
                else:
                    return layer, {"type": "FeatureCollection", "features": features}, "TRUNCATED"
                return layer, {"type": "FeatureCollection", "features": features}, "LIVE_CONNECTED"
            except Exception as exc:
                logger.info("NASA COOLR %s query failed: %s", layer, exc)
                return layer, {"type": "FeatureCollection", "features": features}, "UNAVAILABLE"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda item: query_layer(*item), NASA_COOLR_LAYERS.items()))
        collections = {layer: collection for layer, collection, _ in results}
        statuses = {layer: status for layer, _, status in results}

        connected = any(status in {"LIVE_CONNECTED", "TRUNCATED"} for status in statuses.values())
        return {
            "status": "LIVE_CONNECTED" if connected else "UNAVAILABLE",
            "layers": collections,
            "layer_status": statuses,
            "days": days,
            "bbox": [west, south, east, north],
            "source": "NASA COOLR (reported events; not a road-closure feed)",
        }

    return _cached(cache_key, load, cache_failures=False)


def lhasa_image_url(west: float, south: float, east: float, north: float) -> str:
    """Build an ArcGIS ImageServer export URL for the current LHASA hazard layer."""
    # Approximate the geographic bbox aspect ratio in the requested raster.
    center_lat = (south + north) / 2
    width = max(1.0, min(2048.0, 1024 * abs((east - west) * max(0.15, abs(math.cos(math.radians(center_lat)))) / max(north - south, 0.01))))
    params = urllib.parse.urlencode({
        "bbox": f"{west},{south},{east},{north}", "bboxSR": "4326", "imageSR": "4326",
        "size": f"{int(width)},{1024}", "format": "png32", "f": "image",
        # LHASA uses zero for cells with no current hazard. Exporting those as
        # NoData keeps the regional raster transparent over the basemap.
        "noData": "0", "noDataInterpretation": "esriNoDataMatchAny",
    })
    return f"{NASA_LHASA_TODAY}/exportImage?{params}"


def bbox_for_point(lat: float, lon: float, radius_degrees: float = 0.25) -> List[float]:
    """Return [west, south, east, north], clamped to valid coordinates."""
    return [max(-180.0, lon-radius_degrees), max(-90.0, lat-radius_degrees),
            min(180.0, lon+radius_degrees), min(90.0, lat+radius_degrees)]


def search_places(query: str, state: str) -> Dict[str, Any]:
    """Explicit, bounded place search. Calls the public Nominatim service at <=1 rps."""
    global _LAST_GEOCODE_AT
    if state not in NE_STATE_BOUNDS:
        raise ValueError("Choose one of the eight Northeast states.")
    query = " ".join(query.split())
    if len(query) < 3:
        raise ValueError("Enter at least three characters to search.")
    cache_key = f"{state}:{query.casefold()}"
    if cache_key in _GEOCODE_CACHE:
        return {"state": state, "query": query, "results": _GEOCODE_CACHE[cache_key], "cached": True}

    west, south, east, north = NE_STATE_BOUNDS[state]
    # The selected state's bounding box is the geographic filter. Avoid
    # appending the state/country to a full display-name query, which can
    # duplicate address parts and cause valid Nominatim searches to miss.
    params = urllib.parse.urlencode({"q": query, "format": "jsonv2", "limit": 5,
        "countrycodes": "in", "viewbox": f"{west},{south},{east},{north}", "bounded": 1})
    with _GEOCODE_LOCK:
        delay = 1.05 - (time.monotonic() - _LAST_GEOCODE_AT)
        if delay > 0:
            time.sleep(delay)
        data = _json("https://nominatim.openstreetmap.org/search?" + params,
                     {"User-Agent": USER_AGENT, "Accept-Language": "en"})
        _LAST_GEOCODE_AT = time.monotonic()
    if not isinstance(data, list):
        return {"state": state, "query": query, "results": [], "cached": False,
                "status": "UNAVAILABLE", "attribution": "© OpenStreetMap contributors"}
    results = []
    for item in data:
        try:
            lat, lon = float(item["lat"]), float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if west <= lon <= east and south <= lat <= north:
            results.append({"name": item.get("name") or item.get("display_name"),
                "display_name": item.get("display_name"), "lat": lat, "lon": lon,
                "osm_type": item.get("osm_type"), "osm_id": item.get("osm_id")})
    # Do not keep empty matches indefinitely: the geocoder can update its
    # index, and temporary upstream issues must not become permanent misses.
    if results:
        _GEOCODE_CACHE[cache_key] = results
    return {"state": state, "query": query, "results": results, "cached": False,
            "status": "LIVE_CONNECTED", "attribution": "© OpenStreetMap contributors"}


def get_live_osm_route_roads(bbox: List[float]) -> Dict[str, Any]:
    """Download a bounded, drivable OSM road graph for non-Sikkim trip corridors."""
    west, south, east, north = bbox
    if east-west > 2.0 or north-south > 2.0:
        return {"status": "AREA_TOO_LARGE", "roads": [], "road_count": 0, "bbox": bbox,
                "message": "Choose trip endpoints within a smaller corridor (maximum 2 degrees per side)."}
    key = f"osm-route:{','.join(f'{n:.3f}' for n in bbox)}"
    def load():
        query = (f'[out:json][timeout:25];way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street)$"]'
                 f"({south},{west},{north},{east});out geom;")
        try:
            req = urllib.request.Request("https://overpass-api.de/api/interpreter",
                data=urllib.parse.urlencode({"data": query}).encode(),
                headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=30) as response:
                import json
                data = json.loads(response.read().decode()) if response.status == 200 else None
        except Exception as exc:
            logger.info("Overpass route-network request failed: %s", exc)
            data = None
        if data is None:
            return {"status": "UNAVAILABLE", "roads": [], "road_count": None, "bbox": bbox}
        roads = []
        for item in data.get("elements", []):
            tags = item.get("tags", {})
            geometry = item.get("geometry", [])
            if len(geometry) < 2:
                continue
            roads.append({"id": item.get("id"), "name": tags.get("name") or tags.get("ref") or tags.get("highway", "Road"),
                "risk": 0.0, "route_type": tags.get("highway", "road"),
                "oneway": tags.get("oneway", False),
                "geometry": {"type": "LineString", "coordinates": [[p["lon"], p["lat"]] for p in geometry]}})
        return {"status": "LIVE_CONNECTED", "roads": roads, "road_count": len(roads), "bbox": bbox}
    return _cached(key, load)


def get_osrm_routes(start: List[float], destination: List[float]) -> Dict[str, Any]:
    """Request driving routes from OSRM, adding Valhalla alternatives when needed."""
    global _LAST_OSRM_AT
    base = os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org").rstrip("/")
    coordinates = f"{start[0]},{start[1]};{destination[0]},{destination[1]}"
    url = f"{base}/route/v1/driving/{coordinates}?alternatives=3&overview=simplified&geometries=geojson&steps=false&generate_hints=false"
    key = f"osrm:{coordinates}"
    def load():
        import json

        def decode_shape(encoded):
            points, index, lat, lon = [], 0, 0, 0
            while index < len(encoded):
                values = []
                for _ in range(2):
                    shift = result = 0
                    while True:
                        if index >= len(encoded):
                            raise ValueError("Invalid encoded route geometry")
                        byte = ord(encoded[index]) - 63
                        index += 1
                        result |= (byte & 0x1f) << shift
                        shift += 5
                        if byte < 0x20:
                            break
                    values.append(~(result >> 1) if result & 1 else result >> 1)
                lat += values[0]
                lon += values[1]
                points.append([lon / 1_000_000, lat / 1_000_000])
            return points

        def is_distinct(candidate, existing):
            """Reject same-road variants that only differ in geometry simplification."""
            a, b = candidate.get("coordinates", []), existing.get("coordinates", [])
            if len(a) < 2 or len(b) < 2:
                return False
            separated = 0
            for sample in range(20):
                ai = round(sample * (len(a) - 1) / 19)
                bi = round(sample * (len(b) - 1) / 19)
                if abs(a[ai][0] - b[bi][0]) + abs(a[ai][1] - b[bi][1]) > 0.004:
                    separated += 1
            return separated >= 4

        def valhalla_routes():
            valhalla_base = os.getenv("VALHALLA_BASE_URL", "https://valhalla1.openstreetmap.de").rstrip("/")
            request_data = {"locations": [
                {"lon": float(start[0]), "lat": float(start[1])},
                {"lon": float(destination[0]), "lat": float(destination[1])}],
                "costing": "auto", "units": "kilometers", "alternates": 2,
                "format": "osrm", "shape_format": "geojson", "directions_type": "none"}
            valhalla_url = f"{valhalla_base}/route?json={urllib.parse.quote(json.dumps(request_data, separators=(',', ':')))}"
            try:
                body = _fetch(valhalla_url, timeout=6.0)
                response = json.loads(body.decode("utf-8")) if body else None
            except (ValueError, UnicodeDecodeError, TypeError) as exc:
                logger.info("Valhalla route response could not be decoded: %s", exc)
                return []
            except Exception as exc:
                logger.info("Valhalla route request failed: %s", exc)
                return []
            candidates = response.get("routes", []) if response else []
            converted = []
            for item in candidates:
                shape = item.get("geometry", {})
                coords = shape.get("coordinates", []) if isinstance(shape, dict) else []
                if len(coords) >= 2:
                    converted.append({"coordinates": coords,
                        "distance_km": round(float(item.get("distance", 0)) / 1000, 2),
                        "duration_minutes": round(float(item.get("duration", 0)) / 60),
                        "risk_score": None, "risk_probability": None, "risk_indicator": None,
                        "risk_level": "UNKNOWN", "risk_factors": [], "segments": []})
            # Some Valhalla deployments return native JSON despite format=osrm.
            trip = (response or {}).get("trip", {})
            alternates = trip.get("alternates", []) or (response or {}).get("alternates", [])
            native_trips = [trip, *(item.get("trip", item) for item in alternates)]
            for candidate in native_trips:
                legs = candidate.get("legs", [])
                if not legs:
                    continue
                try:
                    coords = decode_shape(legs[0].get("shape", ""))
                except (IndexError, TypeError, ValueError):
                    continue
                if len(coords) >= 2:
                    summary = candidate.get("summary", {})
                    converted.append({"coordinates": coords,
                        "distance_km": round(float(summary.get("length", 0)), 2),
                        "duration_minutes": round(float(summary.get("time", 0)) / 60),
                        "risk_score": None, "risk_probability": None, "risk_indicator": None,
                        "risk_level": "UNKNOWN", "risk_factors": [], "segments": []})
            return converted

        try:
            with _OSRM_LOCK:
                delay = 1.05 - (time.monotonic() - _LAST_OSRM_AT)
                if delay > 0:
                    time.sleep(delay)
                body = _fetch(url, timeout=3.5)
                _LAST_OSRM_AT = time.monotonic()
            data = json.loads(body.decode()) if body else None
        except Exception as exc:
            logger.info("OSRM route request failed: %s", exc)
            data = None
        routes=[]
        for route in (data or {}).get("routes", [])[:3]:
            coordinates = (route.get("geometry") or {}).get("coordinates", [])
            if len(coordinates) < 2:
                continue
            routes.append({"coordinates":coordinates,
                "distance_km":round(float(route.get("distance",0))/1000,2),
                "duration_minutes":round(float(route.get("duration",0))/60),
                "risk_score":None,"risk_probability":None,"risk_indicator":None,
                "risk_level":"UNKNOWN","risk_factors":[],"segments":[]})
        provider = "OSRM / OpenStreetMap" if routes else None
        if len(routes) < 2:
            for candidate in valhalla_routes():
                if all(is_distinct(candidate, route) for route in routes):
                    routes.append(candidate)
                if len(routes) >= 2:
                    provider = "OSRM and Valhalla / OpenStreetMap" if provider else "Valhalla / OpenStreetMap"
                    break
        if not routes:
            return {"status":"UNAVAILABLE", "routes":[], "message":"Both live driving route services are unavailable."}
        return {"status":"LIVE_CONNECTED", "routes":routes[:2], "message":None, "provider":provider}
    return _cached(key, load, cache_failures=False)


def get_route_weather_conditions(coordinates: List[List[float]]) -> Dict[str, Any]:
    """Fetch current weather/visibility at start, midpoint and end of a route."""
    if not coordinates:
        return {"status": "NO_ROUTE", "points": []}
    samples = [("Start", 0)]
    if len(coordinates) > 2:
        samples.append(("Midpoint", len(coordinates)//2))
    if len(coordinates) > 1:
        samples.append(("Destination", len(coordinates)-1))
    points = [{"position": label, "lon": float(coordinates[index][0]), "lat": float(coordinates[index][1])}
              for label, index in samples]
    jobs = []
    with ThreadPoolExecutor(max_workers=max(1, len(points)*2)) as pool:
        for point in points:
            jobs.append((point, pool.submit(get_live_rainfall_openmeteo, point["lat"], point["lon"]),
                         pool.submit(get_live_weather_openweather, point["lat"], point["lon"])))
        results = []
        for point, meteo_job, weather_job in jobs:
            meteo, weather = meteo_job.result(), weather_job.result()
            results.append({**point,
                "status": "LIVE_CONNECTED" if meteo.get("status") == "LIVE_CONNECTED" else meteo.get("status"),
                "rainfall_mm": meteo.get("rainfall_mm"), "temperature_c": meteo.get("temperature_c"),
                "rainfall_24h_mm": meteo.get("rainfall_24h_mm"),
                "rainfall_72h_mm": meteo.get("rainfall_72h_mm"),
                "humidity": meteo.get("humidity"), "wind_speed_kmh": meteo.get("wind_speed_kmh"),
                "visibility_km": weather.get("visibility_km") if weather.get("visibility_km") is not None else meteo.get("visibility_km"),
                "visibility_status": weather.get("status") if weather.get("visibility_km") is not None else meteo.get("status"),
                "condition": weather.get("condition"), "observed_at": meteo.get("observation_time")})
    connected = any(point["status"] == "LIVE_CONNECTED" for point in results)
    return {"status": "LIVE_CONNECTED" if connected else "UNAVAILABLE", "points": results,
            "summary": {"maximum_rainfall_mm": max((p["rainfall_mm"] for p in results if p["rainfall_mm"] is not None), default=None),
                        "maximum_rainfall_24h_mm": max((p["rainfall_24h_mm"] for p in results if p["rainfall_24h_mm"] is not None), default=None),
                        "maximum_rainfall_72h_mm": max((p["rainfall_72h_mm"] for p in results if p["rainfall_72h_mm"] is not None), default=None),
                        "minimum_visibility_km": min((p["visibility_km"] for p in results if p["visibility_km"] is not None), default=None)}}


def get_live_rainfall_openmeteo(lat: float, lon: float) -> Dict[str, Any]:
    key = f"openmeteo:{lat:.3f}:{lon:.3f}"
    def load():
        params = urllib.parse.urlencode({"latitude": lat, "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,precipitation,rain,weather_code,wind_speed_10m",
            "hourly": "precipitation,visibility", "past_hours": 72, "forecast_hours": 1})
        data = _json("https://api.open-meteo.com/v1/forecast?" + params, timeout=3.0)
        if not data or "current" not in data:
            return {"source":"Open-Meteo", "status":"UNAVAILABLE", "lat":lat,"lon":lon,"rainfall_mm":None}
        c = data["current"]
        hourly = data.get("hourly", {})
        visibility_km = None
        current_hour = str(c.get("time", ""))[:13]
        rainfall_24h_mm = None
        rainfall_72h_mm = None
        try:
            current_dt = datetime.fromisoformat(str(c.get("time", "")))
            recent_rain = []
            for hour, value in zip(hourly.get("time", []), hourly.get("precipitation", [])):
                hour_dt = datetime.fromisoformat(str(hour))
                if value is not None and current_dt - timedelta(hours=72) < hour_dt <= current_dt:
                    recent_rain.append((hour_dt, float(value)))
            rainfall_24h_mm = round(sum(value for hour_dt, value in recent_rain
                                        if hour_dt > current_dt - timedelta(hours=24)), 1)
            rainfall_72h_mm = round(sum(value for _, value in recent_rain), 1)
        except (TypeError, ValueError):
            pass
        for index, hour in enumerate(hourly.get("time", [])):
            if str(hour)[:13] == current_hour and index < len(hourly.get("visibility", [])):
                value = hourly["visibility"][index]
                visibility_km = float(value) / 1000 if value is not None else None
                break
        return {"source":"Open-Meteo", "status":"LIVE_CONNECTED", "lat":lat,"lon":lon,
            "rainfall_mm":c.get("precipitation"), "rain_mm":c.get("rain"),
            "rainfall_24h_mm":rainfall_24h_mm, "rainfall_72h_mm":rainfall_72h_mm,
            "temperature_c":c.get("temperature_2m"), "humidity":c.get("relative_humidity_2m"),
            "wind_speed_kmh":c.get("wind_speed_10m"), "weather_code":c.get("weather_code"),
            "visibility_km":visibility_km,"visibility_source":"Open-Meteo hourly forecast" if visibility_km is not None else None,
            "observation_time":c.get("time"), "units":data.get("current_units", {})}
    return _cached(key, load)


def get_live_weather_openweather(lat: float, lon: float) -> Dict[str, Any]:
    key = f"openweather:{lat:.3f}:{lon:.3f}"
    def load():
        token = os.getenv("OPENWEATHER_API_KEY")
        if not token:
            return {"source":"OpenWeather", "status":"NOT_CONFIGURED", "visibility_km":None,
                    "message":"Set OPENWEATHER_API_KEY to enable this feed."}
        params = urllib.parse.urlencode({"lat":lat,"lon":lon,"appid":token,"units":"metric"})
        data = _json("https://api.openweathermap.org/data/2.5/weather?" + params, timeout=3.0)
        if not data or "main" not in data:
            return {"source":"OpenWeather", "status":"UNAVAILABLE", "visibility_km":None}
        return {"source":"OpenWeather", "status":"LIVE_CONNECTED", "temperature_c":data["main"].get("temp"),
            "humidity":data["main"].get("humidity"), "visibility_km":(data.get("visibility")/1000 if data.get("visibility") is not None else None),
            "condition":(data.get("weather") or [{}])[0].get("description"), "observation_time":data.get("dt")}
    return _cached(key, load)


def get_live_nasa_eonet_events(bbox: List[float], days: int = 30) -> Dict[str, Any]:
    west,south,east,north = bbox
    key = f"eonet:{','.join(f'{n:.3f}' for n in bbox)}:{days}"
    def load():
        params = urllib.parse.urlencode({"category":"severeStorms,landslides,floods","days":days,"status":"open",
                                         "bbox":f"{west},{south},{east},{north}"})
        data = _json("https://eonet.gsfc.nasa.gov/api/v3/events?" + params, timeout=6.0)
        if data is None:
            return {"source":"NASA EONET v3", "status":"UNAVAILABLE", "events":[], "total_active_events":None,"bbox":bbox}
        events=[]
        for ev in data.get("events",[]):
            geom=(ev.get("geometry") or [{}])[-1]
            events.append({"id":ev.get("id"),"title":ev.get("title"),
                "category":(ev.get("categories") or [{}])[0].get("title"),
                "coordinates":geom.get("coordinates"),"date":geom.get("date"),"link":ev.get("link")})
        return {"source":"NASA EONET v3", "status":"LIVE_CONNECTED", "events":events,
                "total_active_events":len(events),"bbox":bbox}
    return _cached(key, load)


def get_live_nasa_firms_alerts(bbox: List[float]) -> Dict[str, Any]:
    west,south,east,north=bbox
    token=os.getenv("NASA_FIRMS_MAP_KEY")
    if not token:
        return {"source":"NASA FIRMS", "status":"NOT_CONFIGURED", "active_thermal_anomalies":None,
                "bbox":bbox,"message":"Set NASA_FIRMS_MAP_KEY to enable FIRMS area data."}
    key=f"firms:{','.join(f'{n:.3f}' for n in bbox)}"
    def load():
        url=f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{urllib.parse.quote(token)}/VIIRS_SNPP_NRT/{west},{south},{east},{north}/2"
        body=_fetch(url, timeout=5.0)
        if body is None:
            return {"source":"NASA FIRMS", "status":"UNAVAILABLE", "active_thermal_anomalies":None,"bbox":bbox}
        try:
            rows=list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
        except (UnicodeDecodeError,csv.Error):
            rows=[]
        return {"source":"NASA FIRMS", "status":"LIVE_CONNECTED", "active_thermal_anomalies":len(rows),
                "bbox":bbox,"observations":rows[:100],"sensor":"VIIRS_SNPP_NRT"}
    return _cached(key,load)


def get_live_opentopography_terrain(lat: float, lon: float) -> Dict[str, Any]:
    # OpenTopography serves DEM rasters; point sampling requires an explicit DEM request
    # and raster decoding. Avoid inventing a point value or treating key presence as data.
    return {"source":"OpenTopography", "status":"CONFIGURATION_REQUIRED", "lat":lat,"lon":lon,
        "elevation_m":None,"slope_degrees":None,
        "message":"Configure a DEM product and raster sampling job. The local Sikkim DEM is used for static terrain features."}


def get_live_osm_road_status(bbox: List[float]) -> Dict[str, Any]:
    west,south,east,north=bbox
    key=f"osm:{','.join(f'{n:.3f}' for n in bbox)}"
    def load():
        query=f"[out:json][timeout:7];(way[highway]({south},{west},{north},{east}););out geom;"
        # Overpass QL is POSTed to avoid URL length limits.
        try:
            req=urllib.request.Request("https://overpass-api.de/api/interpreter",data=urllib.parse.urlencode({"data":query}).encode(),
                headers={"User-Agent":USER_AGENT,"Content-Type":"application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req,timeout=8) as response:
                import json
                data=json.loads(response.read().decode()) if response.status==200 else None
        except Exception as exc:
            logger.info("Overpass unavailable: %s",exc); data=None
        if data is None:
            return {"source":"OpenStreetMap Overpass", "status":"UNAVAILABLE", "bbox":bbox,"road_count":None,"roads":[]}
        roads=[]
        for item in data.get("elements",[]):
            tags=item.get("tags",{})
            roads.append({"osm_way_id":item.get("id"),"name":tags.get("name"),"highway":tags.get("highway"),
                "surface":tags.get("surface"),"lanes":tags.get("lanes"),"geometry":item.get("geometry",[])})
        return {"source":"OpenStreetMap Overpass", "status":"LIVE_CONNECTED", "bbox":bbox,
                "road_count":len(roads),"roads":roads}
    return _cached(key,load)


def get_live_mosdac_satellite_status() -> Dict[str, Any]:
    configured=bool(os.getenv("MOSDAC_DATASET_ID") and os.getenv("MOSDAC_USERNAME") and os.getenv("MOSDAC_PASSWORD"))
    return {"source":"ISRO MOSDAC", "status":"CONFIGURED_NOT_INGESTED" if configured else "NOT_CONFIGURED",
        "product":os.getenv("MOSDAC_DATASET_ID"),"rainfall_mm":None,"cyclone_alerts":None,
        "message":"Requires MOSDAC account credentials and a selected dataset/product ingestion adapter."}


def get_live_glofas_flood_status(lat: float, lon: float) -> Dict[str, Any]:
    configured=bool(os.getenv("GLOFAS_DATA_URL"))
    return {"source":"Copernicus GloFAS", "status":"CONFIGURED_NOT_INGESTED" if configured else "NOT_CONFIGURED",
        "lat":lat,"lon":lon,"flood_probability":None,
        "message":"Configure a GloFAS/Copernicus product endpoint and licensed data access; no live value is currently ingested."}


def get_live_mapillary_road_condition(bbox: List[float]) -> Dict[str, Any]:
    token=os.getenv("MAPILLARY_ACCESS_TOKEN") or os.getenv("MAPILLARY_CLIENT_TOKEN")
    if not token:
        return {"source":"Mapillary", "status":"NOT_CONFIGURED", "image_count":None,"bbox":bbox,
                "message":"Set MAPILLARY_ACCESS_TOKEN. Imagery availability is not a live road-condition measurement."}
    key=f"mapillary:{','.join(f'{n:.3f}' for n in bbox)}"
    def load():
        params=urllib.parse.urlencode({"fields":"id,captured_at,geometry,compass_angle","bbox":','.join(map(str,bbox)),"limit":100,"access_token":token})
        data=_json("https://graph.mapillary.com/images?"+params, timeout=5.0)
        if data is None:
            return {"source":"Mapillary", "status":"UNAVAILABLE", "image_count":None,"bbox":bbox}
        images=data.get("data",[])
        return {"source":"Mapillary", "status":"LIVE_CONNECTED", "image_count":len(images),"bbox":bbox,
                "images":images,"interpretation":"Recent street imagery metadata only; no road-surface condition classifier is run."}
    return _cached(key,load)


def get_unified_live_data(lat: float, lon: float, bbox: Optional[List[float]]=None) -> Dict[str, Any]:
    bbox=bbox or bbox_for_point(lat,lon)
    jobs = {
        "open_meteo": lambda: get_live_rainfall_openmeteo(lat,lon),
        "open_weather": lambda: get_live_weather_openweather(lat,lon),
        "nasa_eonet": lambda: get_live_nasa_eonet_events(bbox),
        "nasa_firms": lambda: get_live_nasa_firms_alerts(bbox),
        "open_topography": lambda: get_live_opentopography_terrain(lat,lon),
        "open_street_map": lambda: get_live_osm_road_status(bbox),
        "isro_mosdac": get_live_mosdac_satellite_status,
        "copernicus_glofas": lambda: get_live_glofas_flood_status(lat,lon),
        "mapillary": lambda: get_live_mapillary_road_condition(bbox),
    }
    # Independent providers should not make the dashboard wait for a chain of
    # network timeouts. Each adapter keeps its own source status and cache.
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {name: pool.submit(load) for name, load in jobs.items()}
        feeds = {}
        for name, future in futures.items():
            try:
                feeds[name] = future.result()
            except Exception as exc:
                logger.info("Live source %s failed: %s", name, exc)
                feeds[name] = {"status": "UNAVAILABLE", "message": "The source could not be reached."}
    meteo=feeds["open_meteo"]
    weather=feeds["open_weather"]
    return {"timestamp":_now(),"query_location":{"lat":lat,"lon":lon},"bbox":bbox,
        "environmental_summary":{"rainfall_mm":meteo.get("rainfall_mm"),
            "rainfall_24h_mm":meteo.get("rainfall_24h_mm"),
            "rainfall_72h_mm":meteo.get("rainfall_72h_mm"),"visibility_km":weather.get("visibility_km"),
            "temperature_c":meteo.get("temperature_c"),"humidity":meteo.get("humidity"),
            "active_disaster_events":feeds["nasa_eonet"].get("total_active_events")},
        "sources":feeds}
