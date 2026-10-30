"""Live source adapters. Unavailable feeds return null data, never demo values."""

import csv
import io
import logging
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
_CACHE: Dict[str, tuple] = {}
CACHE_TTL_SECONDS = 900
USER_AGENT = "SETU-NER/1.0 (road risk research; contact project maintainers)"


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


def _json(url: str, headers: Optional[Dict[str, str]] = None) -> Optional[dict]:
    import json
    body = _fetch(url, headers)
    if body is None:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def _cached(key: str, loader):
    now = time.time()
    entry = _CACHE.get(key)
    if entry and now - entry[0] < (CACHE_TTL_SECONDS if entry[1].get("status") == "LIVE_CONNECTED" else 60):
        value = dict(entry[1])
        value["cache"] = "HIT"
        return value
    value = loader()
    value.setdefault("timestamp", _now())
    value["cache"] = "MISS"
    _CACHE[key] = (now, dict(value))
    return value


def bbox_for_point(lat: float, lon: float, radius_degrees: float = 0.25) -> List[float]:
    """Return [west, south, east, north], clamped to valid coordinates."""
    return [max(-180.0, lon-radius_degrees), max(-90.0, lat-radius_degrees),
            min(180.0, lon+radius_degrees), min(90.0, lat+radius_degrees)]


def get_live_rainfall_openmeteo(lat: float, lon: float) -> Dict[str, Any]:
    key = f"openmeteo:{lat:.3f}:{lon:.3f}"
    def load():
        params = urllib.parse.urlencode({"latitude": lat, "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,precipitation,rain,weather_code,wind_speed_10m"})
        data = _json("https://api.open-meteo.com/v1/forecast?" + params)
        if not data or "current" not in data:
            return {"source":"Open-Meteo", "status":"UNAVAILABLE", "lat":lat,"lon":lon,"rainfall_mm":None}
        c = data["current"]
        return {"source":"Open-Meteo", "status":"LIVE_CONNECTED", "lat":lat,"lon":lon,
            "rainfall_mm":c.get("precipitation"), "rain_mm":c.get("rain"),
            "temperature_c":c.get("temperature_2m"), "humidity":c.get("relative_humidity_2m"),
            "wind_speed_kmh":c.get("wind_speed_10m"), "weather_code":c.get("weather_code"),
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
        data = _json("https://api.openweathermap.org/data/2.5/weather?" + params)
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
        data = _json("https://eonet.gsfc.nasa.gov/api/v3/events?" + params)
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
        body=_fetch(url)
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
        query=f"[out:json][timeout:20];(way[highway]({south},{west},{north},{east}););out geom;"
        # Overpass QL is POSTed to avoid URL length limits.
        try:
            req=urllib.request.Request("https://overpass-api.de/api/interpreter",data=urllib.parse.urlencode({"data":query}).encode(),
                headers={"User-Agent":USER_AGENT,"Content-Type":"application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req,timeout=25) as response:
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
        data=_json("https://graph.mapillary.com/images?"+params)
        if data is None:
            return {"source":"Mapillary", "status":"UNAVAILABLE", "image_count":None,"bbox":bbox}
        images=data.get("data",[])
        return {"source":"Mapillary", "status":"LIVE_CONNECTED", "image_count":len(images),"bbox":bbox,
                "images":images,"interpretation":"Recent street imagery metadata only; no road-surface condition classifier is run."}
    return _cached(key,load)


def get_unified_live_data(lat: float, lon: float, bbox: Optional[List[float]]=None) -> Dict[str, Any]:
    bbox=bbox or bbox_for_point(lat,lon)
    feeds={
        "open_meteo":get_live_rainfall_openmeteo(lat,lon),
        "open_weather":get_live_weather_openweather(lat,lon),
        "nasa_eonet":get_live_nasa_eonet_events(bbox),
        "nasa_firms":get_live_nasa_firms_alerts(bbox),
        "open_topography":get_live_opentopography_terrain(lat,lon),
        "open_street_map":get_live_osm_road_status(bbox),
        "isro_mosdac":get_live_mosdac_satellite_status(),
        "copernicus_glofas":get_live_glofas_flood_status(lat,lon),
        "mapillary":get_live_mapillary_road_condition(bbox),
    }
    meteo=feeds["open_meteo"]
    weather=feeds["open_weather"]
    return {"timestamp":_now(),"query_location":{"lat":lat,"lon":lon},"bbox":bbox,
        "environmental_summary":{"rainfall_mm":meteo.get("rainfall_mm"),"visibility_km":weather.get("visibility_km"),
            "temperature_c":meteo.get("temperature_c"),"humidity":meteo.get("humidity"),
            "active_disaster_events":feeds["nasa_eonet"].get("total_active_events")},
        "sources":feeds}
