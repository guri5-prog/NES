import { useCallback, useEffect, useState } from "react";
import MapView from "./components/MapView";
import AlertPanel from "./components/AlertPanel";
import IncidentForm from "./components/IncidentForm";
import NotificationPanel from "./components/NotificationPanel";
import AuthPage from "./components/AuthPage";
import RouteConditionsPanel from "./components/RouteConditionsPanel";
import "./App.css";

const API_URL = import.meta.env.VITE_API_URL ?? "";
const NORTHEAST_STATES = ["Arunachal Pradesh", "Assam", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Sikkim", "Tripura"];

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_URL}${path}`, {
    credentials: "include",
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) throw Object.assign(new Error("Your session has expired. Please sign in again."), { status: 401 });
    const detail = typeof data.detail === "string" ? data.detail : data.detail?.message || `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return data;
}

function App() {
  const [user, setUser] = useState(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [dashboard, setDashboard] = useState({ network: null, routes: null, vehicles: [], incidents: [] });
  const [backendOnline, setBackendOnline] = useState(false);
  const [loadingDashboard, setLoadingDashboard] = useState(false);
  const [dashboardError, setDashboardError] = useState("");
  const [selectedRoute, setSelectedRoute] = useState("normal");
  const [lastUpdated, setLastUpdated] = useState(null);
  const [signingOut, setSigningOut] = useState(false);
  const [liveSources, setLiveSources] = useState(null);
  const [liveSourcesError, setLiveSourcesError] = useState("");
  const [loadingLiveSources, setLoadingLiveSources] = useState(false);
  const [trip, setTrip] = useState({
    originState: "Sikkim",
    destinationState: "Sikkim",
    originQuery: "Gangtok",
    destinationQuery: "Namchi",
    origin: { name: "Gangtok", lat: 27.3389, lon: 88.6138 },
    destination: { name: "Namchi", lat: 27.1667, lon: 88.3639 },
  });
  const [placeResults, setPlaceResults] = useState({ origin: [], destination: [] });
  const [searchingPlace, setSearchingPlace] = useState("");
  const [searchingRoute, setSearchingRoute] = useState(false);
  const [routeSearchError, setRouteSearchError] = useState("");
  const [landslideData, setLandslideData] = useState(null);
  const [loadingLandslides, setLoadingLandslides] = useState(false);
  const [landslideError, setLandslideError] = useState("");
  const [showCoolr, setShowCoolr] = useState(false);
  const [showLhasa, setShowLhasa] = useState(false);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 4000);

    apiRequest("/api/auth/session", { signal: controller.signal })
      .then((data) => { if (active) setUser(data.user ?? null); })
      .catch(() => { if (active) setUser(null); })
      .finally(() => {
        clearTimeout(timer);
        if (active) setAuthChecking(false);
      });

    return () => {
      active = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, []);

  const loadDashboard = useCallback(async () => {
    setLoadingDashboard(true);
    setDashboardError("");
    const requests = [
      ["network", "/api/network", (data) => data],
      ["routes", "/api/routes", (data) => data],
      ["vehicles", "/api/vehicles", (data) => Array.isArray(data) ? data : (data.vehicles ?? [])],
      ["incidents", "/api/incidents", (data) => Array.isArray(data) ? data : (data.incidents ?? [])],
    ];
    try {
      const results = await Promise.all(requests.map(async ([key, path, normalize]) => {
        try {
          const value = normalize(await apiRequest(path));
          setDashboard((current) => ({ ...current, [key]: value }));
          setBackendOnline(true);
          setLastUpdated(new Date());
          return { key, error: null };
        } catch (error) {
          if (error.status === 401) setUser(null);
          return { key, error };
        }
      }));
      const successful = results.filter((result) => !result.error);
      const failed = results.filter((result) => result.error);
      setBackendOnline(successful.length > 0);
      if (!successful.length) setDashboardError(failed[0]?.error?.message || "Could not load dashboard data.");
      else if (failed.length) setDashboardError(`Some dashboard data is unavailable: ${failed.map((result) => result.key).join(", ")}.`);
    } finally {
      setLoadingDashboard(false);
    }
  }, []);

  useEffect(() => {
    if (user) loadDashboard();
  }, [user, loadDashboard]);

  const refreshLiveSources = useCallback(() => {
    let active = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    setLoadingLiveSources(true);
    setLiveSourcesError("");
    apiRequest("/api/live-sources", { signal: controller.signal })
      .then((data) => {
        if (active) {
          setLiveSources(data.sources ?? {});
          setLiveSourcesError("");
        }
      })
      .catch((error) => {
        if (!active) return;
        setLiveSourcesError(controller.signal.aborted
          ? "Live-source checks timed out. Retry to check the providers again."
          : error.message || "Live-source status is unavailable.");
      })
      .finally(() => {
        clearTimeout(timer);
        if (active) setLoadingLiveSources(false);
      });
    return () => {
      active = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, []);

  useEffect(() => {
    if (!user) return undefined;
    return refreshLiveSources();
  }, [user, refreshLiveSources]);

  async function handleLogout() {
    setSigningOut(true);
    try {
      await apiRequest("/api/auth/logout", { method: "POST" });
      setUser(null);
    } catch (error) {
      setDashboardError(error.message || "Could not sign out.");
    } finally { setSigningOut(false); }
  }

  async function handleIncidentAdded(incident) {
    setDashboard((current) => ({ ...current, incidents: [incident, ...current.incidents] }));
    try {
      const [routes, incidents] = await Promise.all([
        apiRequest("/api/routes"), apiRequest("/api/incidents"),
      ]);
      setDashboard((current) => ({ ...current, routes, incidents: incidents.incidents ?? [] }));
    } catch { /* Keep the successfully submitted incident visible if a follow-up read fails. */ }
  }

  function updateTrip(field, value) {
    setRouteSearchError("");
    if (field === "originState" || field === "destinationState") {
      const endpoint = field === "originState" ? "origin" : "destination";
      const queryField = `${endpoint}Query`;
      setTrip((current) => ({ ...current, [field]: value, [endpoint]: null, [queryField]: "" }));
      setPlaceResults((current) => ({ ...current, [endpoint]: [] }));
    } else if (field.endsWith("Query")) {
      const endpoint = field === "originQuery" ? "origin" : "destination";
      setTrip((current) => ({ ...current, [field]: value, [endpoint]: null }));
      setPlaceResults((current) => ({ ...current, [endpoint]: [] }));
    } else {
      setTrip((current) => ({ ...current, [field]: value }));
    }
  }

  async function searchPlace(endpoint) {
    const query = endpoint === "origin" ? trip.originQuery : trip.destinationQuery;
    if (!query || query.trim().length < 3) { setRouteSearchError("Enter at least three characters for a place search."); return; }
    setSearchingPlace(endpoint);
    setRouteSearchError("");
    try {
      const selectedState = trip[`${endpoint}State`];
      const params = new URLSearchParams({ q: query.trim(), state: selectedState });
      const data = await apiRequest(`/api/places/search?${params}`);
      setPlaceResults((current) => ({ ...current, [endpoint]: data.results ?? [] }));
      if (data.status === "UNAVAILABLE") setRouteSearchError(`The OpenStreetMap place search is unavailable right now. Try again shortly.`);
      else if (!data.results?.length) setRouteSearchError(`No matching places found in ${selectedState}. Try a shorter place name, such as a town or city.`);
    } catch (error) {
      setRouteSearchError(error.message || "Place search failed.");
    } finally { setSearchingPlace(""); }
  }

  async function calculateTrip(event) {
    event.preventDefault();
    if (!trip.origin || !trip.destination) {
      setRouteSearchError("Search for and choose both an origin and destination first.");
      return;
    }
    setSearchingRoute(true);
    setRouteSearchError("");
    // Remove the previous trip immediately so a failed lookup cannot leave
    // routes and a map from a different origin/destination on screen.
    setDashboard((current) => ({ ...current, routes: null, network: null }));
    setLandslideData(null);
    setShowCoolr(false);
    setShowLhasa(false);
    setLandslideError("");
    try {
      const params = new URLSearchParams({
        state: trip.originState === trip.destinationState ? trip.originState : "Northeast India",
        origin_state: trip.originState,
        destination_state: trip.destinationState,
        start_lon: String(trip.origin.lon), start_lat: String(trip.origin.lat),
        destination_lon: String(trip.destination.lon), destination_lat: String(trip.destination.lat),
      });
      const routes = await apiRequest(`/api/routes?${params}`);
      let network = routes.network ?? null;
      if (!network && routes.area?.bbox) {
        const [west, south, east, north] = routes.area.bbox;
        const networkParams = new URLSearchParams({ state: trip.originState, west, south, east, north });
        try { network = await apiRequest(`/api/network?${networkParams}`); } catch { /* The route remains visible if the map network fetch is unavailable. */ }
      }
      setDashboard((current) => ({ ...current, routes, network }));
      setSelectedRoute("normal");
    } catch (error) {
      setRouteSearchError(typeof error.message === "string" ? error.message : "Could not calculate routes for this area.");
    } finally { setSearchingRoute(false); }
  }

  async function loadLandslides() {
    const coordinates = [
      ...(dashboard.routes?.normal?.coordinates ?? []),
      ...(dashboard.routes?.safer?.coordinates ?? []),
    ].filter((point) => Array.isArray(point) && Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1])));
    if (coordinates.length < 2) {
      setLandslideError("Find a route before loading landslide data.");
      return;
    }
    setLoadingLandslides(true);
    setLandslideError("");
    try {
      const pad = 0.12;
      const west = Math.min(...coordinates.map(([lon]) => Number(lon))) - pad;
      const east = Math.max(...coordinates.map(([lon]) => Number(lon))) + pad;
      const south = Math.min(...coordinates.map(([, lat]) => Number(lat))) - pad;
      const north = Math.max(...coordinates.map(([, lat]) => Number(lat))) + pad;
      const params = new URLSearchParams({ west, south, east, north, days: "7" });
      const data = await apiRequest(`/api/landslides?${params}`);
      setLandslideData(data);
      setShowCoolr(true);
      setShowLhasa(false);
      if (data.status === "UNAVAILABLE") setLandslideError("NASA COOLR is temporarily unavailable. You can still try the LHASA hazard layer.");
    } catch (error) {
      setLandslideError(error.message || "Could not load NASA landslide layers.");
    } finally {
      setLoadingLandslides(false);
    }
  }

  function choosePlace(endpoint, place) {
    const queryField = endpoint === "origin" ? "originQuery" : "destinationQuery";
    setTrip((current) => ({ ...current, [endpoint]: place, [queryField]: place.display_name || place.name }));
    setPlaceResults((current) => ({ ...current, [endpoint]: [] }));
    setRouteSearchError("");
  }

  if (authChecking) return <main className="auth-page"><p className="auth-loading">Checking your session…</p></main>;
  if (!user) return <AuthPage onAuthenticated={setUser} />;

  const { network, routes, vehicles, incidents } = dashboard;
  const selectedConditions = routes?.route_conditions?.[selectedRoute];
  const routeRainfall = selectedConditions?.summary?.maximum_rainfall_mm;
  const highSeverity = incidents.filter((incident) => String(incident.severity).toUpperCase() === "HIGH").length;
  const coolrPointCount = landslideData?.layers?.points?.features?.length ?? 0;
  const coolrAreaCount = landslideData?.layers?.polygons?.features?.length ?? 0;

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#dashboard" aria-label="Northstar dashboard home">
          <span className="brand-mark">N</span>
          <span><strong>Northstar</strong><small>LOGISTICS INTELLIGENCE</small></span>
        </a>
        <div className="topbar-right">
          <div className={`connection ${backendOnline ? "is-online" : "is-offline"}`}>
            <span className="status-dot" />{backendOnline ? "Systems connected" : "Systems unavailable"}
          </div>
          <button className="refresh-button" type="button" onClick={loadDashboard} disabled={loadingDashboard}>
            <span aria-hidden="true">↻</span> {loadingDashboard ? "Refreshing" : "Refresh data"}
          </button>
          <div className="user-menu"><span className="avatar">{user.name?.slice(0, 1)?.toUpperCase() || "U"}</span><span className="user-name">{user.name}</span>
            <button type="button" onClick={handleLogout} disabled={signingOut}>{signingOut ? "Signing out…" : "Sign out"}</button>
          </div>
        </div>
      </header>

      <main id="dashboard" className="workspace">
        <section className="page-heading">
          <div><p className="eyebrow">OPERATIONS OVERVIEW</p><h1>Good day, {user.name?.split(" ")[0] || "operator"}</h1>
            <p className="heading-copy">Monitor route conditions, active incidents, and fleet movement.</p></div>
          <div className="update-time">{lastUpdated ? <>Updated {lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</> : "Waiting for data"}</div>
        </section>

        {dashboardError && <div className="error-banner" role="alert"><strong>Dashboard data unavailable</strong><span>{dashboardError}</span><button type="button" onClick={loadDashboard}>Try again</button></div>}

        <form className="panel-card trip-search" onSubmit={calculateTrip}>
          <div className="card-heading"><div><p className="eyebrow">NORTHEAST INDIA ROUTE SEARCH</p><h2>Choose a start and destination</h2></div></div>
          <div className="trip-search-grid">
            {["origin", "destination"].map((endpoint) => {
              const queryField = endpoint === "origin" ? "originQuery" : "destinationQuery";
              const stateField = endpoint === "origin" ? "originState" : "destinationState";
              const title = endpoint === "origin" ? "Start location" : "Destination";
              return <div className="trip-field" key={endpoint}><label htmlFor={`${endpoint}-place`}>{title}</label><div className="trip-endpoint-controls"><select aria-label={`${title} state`} value={trip[stateField]} onChange={(event) => updateTrip(stateField, event.target.value)}>{NORTHEAST_STATES.map((state) => <option key={state}>{state}</option>)}</select><div className="trip-place-field"><input id={`${endpoint}-place`} value={trip[queryField]} onChange={(event) => updateTrip(queryField, event.target.value)} placeholder={`Search in ${trip[stateField]}`} /><button type="button" onClick={() => searchPlace(endpoint)} disabled={searchingPlace !== ""}>{searchingPlace === endpoint ? "Searching" : "Find"}</button></div></div>
                {placeResults[endpoint].length > 0 && <div className="place-results">{placeResults[endpoint].map((place) => <button className="place-result" type="button" key={`${place.osm_type}-${place.osm_id}-${place.lat}`} onClick={() => choosePlace(endpoint, place)}>{place.display_name}</button>)}</div>}
              </div>;
            })}
            <button className="trip-submit" type="submit" disabled={searchingRoute}>{searchingRoute ? "Finding routes…" : "Find routes"}</button>
          </div>
          {routeSearchError && <p className="trip-search-error" role="alert">{routeSearchError}</p>}
          <p className="source-status-note">Place search uses OpenStreetMap data. © OpenStreetMap contributors.</p>
        </form>

        <section className="metric-grid" aria-label="Operations summary">
          <article className="metric-card"><span className="metric-icon blue">↗</span><div><span className="metric-label">Tracked vehicles</span><strong>{vehicles.length}</strong><small>Vehicles reporting position</small></div></article>
          <article className="metric-card"><span className="metric-icon amber">⌁</span><div><span className="metric-label">Active incidents</span><strong>{incidents.length}</strong><small>{highSeverity} high severity</small></div></article>
          <article className="metric-card"><span className="metric-icon violet">☂</span><div><span className="metric-label">Route rainfall</span><strong>{routeRainfall ?? "—"}<small className="metric-unit"> mm</small></strong><small>{selectedConditions?.status === "LIVE_CONNECTED" ? "Along the selected route" : "No current reading"}</small></div></article>
          <article className="metric-card"><span className="metric-icon green">⌖</span><div><span className="metric-label">Road network</span><strong>{network?.features?.length ?? "—"}</strong><small>Mapped road segments</small></div></article>
        </section>

        <section className="content-grid">
          <div className="map-card">
            <div className="card-heading map-heading"><div><p className="eyebrow">LIVE MAP</p><h2>Route and fleet map</h2></div>
              <div className="map-heading-actions">
                <div className="route-switch" role="group" aria-label="Select route">
                  <button className={selectedRoute === "normal" ? "selected primary" : ""} onClick={() => setSelectedRoute("normal")} type="button"><i className="route-key primary-key" />Primary</button>
                  <button className={selectedRoute === "safer" ? "selected safer" : ""} onClick={() => setSelectedRoute("safer")} type="button" disabled={routes?.has_alternative === false}><i className="route-key safer-key" />Alternative</button>
                </div>
                <div className="landslide-controls">
                  <button type="button" className="landslide-load-button" onClick={loadLandslides} disabled={loadingLandslides || !routes}>{loadingLandslides ? "Loading NASA layers…" : "Load landslides (7 days)"}</button>
                  {landslideData && <>
                    <label><input type="checkbox" checked={showCoolr} onChange={(event) => setShowCoolr(event.target.checked)} /> Reported landslides ({coolrPointCount + coolrAreaCount})</label>
                    <label><input type="checkbox" checked={showLhasa} onChange={(event) => setShowLhasa(event.target.checked)} /> LHASA current hazard</label>
                  </>}
                </div>
              </div>
            </div>
            {landslideError && <p className="trip-search-error landslide-message" role="status">{landslideError}</p>}
            {landslideData && <p className="source-status-note landslide-source-note">{landslideData.status === "UNAVAILABLE" ? "NASA COOLR could not be reached. " : coolrPointCount + coolrAreaCount === 0 ? "No NASA COOLR reports or mapped areas were returned for this route in the last 7 days. " : `Loaded ${coolrPointCount} reported point(s) and ${coolrAreaCount} mapped area(s) from the last 7 days. `}COOLR reports are not verified road closures. LHASA is a separate regional hazard nowcast, not a road-level disruption probability.</p>}
            <div className="map-frame"><MapView network={network} routes={routes} vehicles={vehicles} incidents={incidents} selectedRoute={selectedRoute} onSelectRoute={setSelectedRoute} landslideData={landslideData} showCoolr={showCoolr} showLhasa={showLhasa} /></div>
            <div className="map-footer"><span><i className="legend-line road-legend" />Road network</span><span><i className="legend-line primary-legend" />Primary route</span><span><i className="legend-line safer-legend" />Alternative route</span><span><i className="legend-dot incident-legend" />Incident</span></div>
          </div>

          <aside className="side-column">
            <AlertPanel routes={routes} selectedRoute={selectedRoute} onSelectRoute={setSelectedRoute} />
            <div className="panel-card live-source-panel"><div className="card-heading"><div><p className="eyebrow">EXTERNAL FEEDS</p><h2>Live source status</h2></div><button className="text-button source-refresh-button" type="button" onClick={refreshLiveSources} disabled={loadingLiveSources}>{loadingLiveSources ? "Checking…" : "Refresh status"}</button></div>
              {liveSourcesError ? <p className="empty-state">{liveSourcesError}</p> : !liveSources ? <p className="empty-state">Checking configured providers…</p> : <div className="source-status-list">{Object.entries(liveSources).map(([key, source]) => <div className="source-status-row" key={key}><span>{({open_meteo:"Open-Meteo",open_weather:"OpenWeather",nasa_eonet:"NASA EONET",nasa_firms:"NASA FIRMS",open_topography:"OpenTopography",open_street_map:"OpenStreetMap",isro_mosdac:"MOSDAC",copernicus_glofas:"GloFAS",mapillary:"Mapillary"})[key] ?? key}</span><span className={`source-status ${String(source.status || "UNKNOWN").toLowerCase()}`}>{source.status || "UNKNOWN"}</span></div>)}</div>}
              <p className="source-status-note">Only LIVE CONNECTED feeds contain an upstream observation. Other providers need credentials or product setup.</p>
            </div>
            <div className="panel-card incident-create"><div className="card-heading"><div><p className="eyebrow">FIELD REPORT</p><h2>Report an incident</h2></div><span className="form-icon">＋</span></div>
              <IncidentForm onIncidentAdded={handleIncidentAdded} /></div>
          </aside>
        </section>

        <RouteConditionsPanel routes={routes} selectedRoute={selectedRoute} />

        <section className="lower-grid">
          <div className="panel-card"><div className="card-heading"><div><p className="eyebrow">FLEET</p><h2>Vehicle status</h2></div><span className="count-pill">{vehicles.length} total</span></div>
            {vehicles.length ? <div className="table-wrap"><table><thead><tr><th>Vehicle</th><th>Driver / cargo</th><th>Speed</th><th>Status</th></tr></thead><tbody>{vehicles.map((vehicle, index) => <tr key={vehicle.id ?? index}><td><span className="vehicle-code"><span className="vehicle-dot" />{vehicle.id ?? `Vehicle ${index + 1}`}</span></td><td><strong>{vehicle.driver || "—"}</strong><small>{vehicle.cargo || "No cargo details"}</small></td><td>{vehicle.speed ?? "—"}<small> km/h</small></td><td><span className={`status-pill ${String(vehicle.status || "unknown").toLowerCase()}`}>{vehicle.status || "Unknown"}</span></td></tr>)}</tbody></table></div> : <p className="empty-state">Vehicle positions will appear here when the API reports them.</p>}
          </div>
          <div className="panel-card incident-list-card"><div className="card-heading"><div><p className="eyebrow">SITUATIONAL AWARENESS</p><h2>Recent incidents</h2></div><span className="count-pill">{incidents.length} active</span></div>
            <NotificationPanel incidents={incidents} />
          </div>
        </section>
        <footer className="page-footer"><span>Northstar Logistics Intelligence</span><span>Risk-aware operations dashboard</span></footer>
      </main>
    </div>
  );
}

export default App;
