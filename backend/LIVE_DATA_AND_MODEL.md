# Sikkim live data and model integration

## API behavior

- `GET /api/live-sources?lat=27.5&lon=88.5&radius_degrees=0.65` queries the selected Sikkim area. It returns a separate status for each feed. `LIVE_CONNECTED` means an upstream response was received; `NOT_CONFIGURED`, `CONFIGURATION_REQUIRED`, `CONFIGURED_NOT_INGESTED`, and `UNAVAILABLE` do not contain fabricated measurements.
- `GET /api/weather` fetches current Open-Meteo data near Gangtok and stores only that observation in PostgreSQL. Visibility is left null because Open-Meteo is not the visibility source in this integration.
- `GET /api/routes` uses the checked-in Sikkim OSM road export by default. Route coordinates are `[longitude, latitude]`; start and destination can be supplied as `start_lon`, `start_lat`, `destination_lon`, and `destination_lat`. Set `ROUTE_NETWORK_SOURCE=postgis` only after importing the Sikkim network with `python import_roads.py`.
- `/api/places/search?q=...&state=...` searches submitted place names inside one of the eight Northeast state areas. `/api/routes` accepts `origin_state` and `destination_state`, allowing routes across state borders. Trips within Sikkim use the local Sikkim route graph; other trips use OSRM alternatives and query Valhalla for a distinct alternative when OSRM only returns one. `OSRM_BASE_URL` and `VALHALLA_BASE_URL` can point to project-managed routing servers. The public Nominatim geocoder is queried only on explicit searches and rate-limited to one request per second.
- Route responses contain weather, visibility, and Open-Meteo 24-hour precipitation samples for the start, midpoint, and destination. Sikkim route scores aggregate per-edge heuristic scores weighted by edge length and use incident-to-road-segment distance. External OSM routes score their geometry sections using the nearest of their three weather samples and incidents within 2 km. Neither path currently has full segment-level slope/soil/land-cover features, and neither score is a calibrated disruption probability.
- `GET /api/network` returns the Sikkim road features inside its `west`, `south`, `east`, `north` bounds.
- `GET /api/vehicles` returns persisted fleet records only. It no longer writes demo Shillong vehicle positions.
- `POST /api/susceptibility/predict` accepts `{ "segment_id": "...", "features": { ... } }` with exactly the 24 model columns in `model/models/feature_schema_v3.json` and runs `random_forest_final_v3.joblib`.

## Model meaning and current limit

The trained Random Forest is a Sikkim landslide initiation susceptibility classifier. Its target distinguishes historical landslide inventory points from background samples. It is not a road closure, road disruption, traffic, or live-weather probability model. The endpoint therefore returns `susceptibility_probability` and `disruption_probability: null`. The model metadata also records that acceptance criteria did not pass. Its inference endpoint is consequently marked as research output.

Automatic segment scoring is not yet available: the checked-in road records do not include all 24 input features, and several required terrain derivatives (aspect, curvature, TRI, TPI) are not present as ready-to-sample rasters. The API rejects partial feature vectors instead of filling those values with invented data. The routing engine currently uses a normalized heuristic incident/environment indicator; its legacy `risk_probability` response field is null and `risk_indicator` is explicitly a score. A separate disruption model needs road-segment/time-window labels and validation before that score can be called a probability.

## Source status and configuration

| Feed | Current integration |
| --- | --- |
| Open-Meteo | Live current weather, no key |
| OpenWeather | Live current conditions when `OPENWEATHER_API_KEY` is configured |
| NASA FIRMS | Live VIIRS area observations when `NASA_FIRMS_MAP_KEY` is configured |
| NASA EONET | Live open events filtered to the requested bounding box |
| OpenStreetMap | Live Overpass road tags and geometry, subject to Overpass availability and usage policy |
| OpenTopography | Not yet queried. The repository's aligned Sikkim DEM and slope rasters supply static terrain data; a DEM product sampling adapter is still required for remote queries. |
| MOSDAC | Requires account/product configuration and a dataset-specific ingestion adapter; status is reported, no value is synthesized. |
| GloFAS | Requires a selected Copernicus product/access path and ingestion adapter; status is reported, no value is synthesized. |
| Mapillary | Live image metadata when `MAPILLARY_ACCESS_TOKEN` is configured; imagery is not classified as a road condition. |
| NASA COOLR | On-demand `/api/landslides?west=...&south=...&east=...&north=...&days=7` queries recent reported points and mapped polygons for the route extent. This is a report catalog, not a guaranteed complete or real-time incident feed and not a closure source. |
| NASA LHASA | The same on-demand endpoint returns a current ImageServer overlay URL. LHASA is shown as an independent regional hazard nowcast; it is not added to the trained model or route score. |

Copy `.env.example` to `.env`, set only the keys you have, then restart the backend. Never commit `.env`. API credentials are read from the process environment.

Install the model inference dependencies from the `backend` directory with `pip install -r requirements-model.txt` before calling `/api/susceptibility/predict`.

The route weights `alpha` and `beta` remain configurable on `/api/routes`; they are not calibrated operational settings. With the current heuristic, the safer route is only a demonstration ranking, not an assurance of lower real-world disruption risk.

The public OSRM endpoint is a best-effort demo service, not a production availability commitment. Its published usage policy asks clients to stay at or below one request per second; this backend serializes and rate-limits route requests. For deployment, point `OSRM_BASE_URL` to an owned or contracted routing service.
