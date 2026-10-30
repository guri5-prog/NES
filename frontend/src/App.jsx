import { useCallback, useEffect, useState } from "react";
import MapView from "./components/MapView";
import AlertPanel from "./components/AlertPanel";
import IncidentForm from "./components/IncidentForm";
import NotificationPanel from "./components/NotificationPanel";
import AuthPage from "./components/AuthPage";
import "./App.css";

const API_URL = import.meta.env.VITE_API_URL ?? "";

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
    throw new Error(data.detail || `Request failed (${response.status})`);
  }
  return data;
}

function App() {
  const [user, setUser] = useState(null);
  const [authChecking, setAuthChecking] = useState(true);
  const [dashboard, setDashboard] = useState({ network: null, routes: null, vehicles: [], weather: null, risk: null, incidents: [] });
  const [backendOnline, setBackendOnline] = useState(false);
  const [loadingDashboard, setLoadingDashboard] = useState(false);
  const [dashboardError, setDashboardError] = useState("");
  const [selectedRoute, setSelectedRoute] = useState("normal");
  const [lastUpdated, setLastUpdated] = useState(null);
  const [signingOut, setSigningOut] = useState(false);
  const [liveSources, setLiveSources] = useState(null);
  const [liveSourcesError, setLiveSourcesError] = useState("");

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
    try {
      // Persist a fresh Open-Meteo observation before updating the dashboard.
      const weather = await apiRequest("/api/weather");
      const [network, routes, vehicles, risk, incidents] = await Promise.all([
        apiRequest("/api/network"),
        apiRequest("/api/routes"),
        apiRequest("/api/vehicles"),
        apiRequest("/api/risk"),
        apiRequest("/api/incidents"),
      ]);
      setDashboard({
        network,
        routes,
        vehicles: Array.isArray(vehicles) ? vehicles : (vehicles.vehicles ?? []),
        weather,
        risk,
        incidents: Array.isArray(incidents) ? incidents : (incidents.incidents ?? []),
      });
      setBackendOnline(true);
      setLastUpdated(new Date());
    } catch (error) {
      setBackendOnline(false);
      if (error.status === 401) setUser(null);
      setDashboardError(error.message || "Could not load dashboard data.");
    } finally {
      setLoadingDashboard(false);
    }
  }, []);

  useEffect(() => {
    if (user) loadDashboard();
  }, [user, loadDashboard]);

  useEffect(() => {
    if (!user) return undefined;
    let active = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 35000);
    apiRequest("/api/live-sources", { signal: controller.signal })
      .then((data) => { if (active) { setLiveSources(data.sources ?? {}); setLiveSourcesError(""); } })
      .catch((error) => { if (active) setLiveSourcesError(error.message || "Live-source status is unavailable."); })
      .finally(() => clearTimeout(timer));
    return () => { active = false; clearTimeout(timer); controller.abort(); };
  }, [user]);

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
      const [routes, risk, incidents] = await Promise.all([
        apiRequest("/api/routes"), apiRequest("/api/risk"), apiRequest("/api/incidents"),
      ]);
      setDashboard((current) => ({ ...current, routes, risk, incidents: incidents.incidents ?? [] }));
    } catch { /* Keep the successfully submitted incident visible if a follow-up read fails. */ }
  }

  if (authChecking) return <main className="auth-page"><p className="auth-loading">Checking your session…</p></main>;
  if (!user) return <AuthPage onAuthenticated={setUser} />;

  const { network, routes, vehicles, weather, risk, incidents } = dashboard;
  const highSeverity = incidents.filter((incident) => String(incident.severity).toUpperCase() === "HIGH").length;

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

        <section className="metric-grid" aria-label="Operations summary">
          <article className="metric-card"><span className="metric-icon blue">↗</span><div><span className="metric-label">Tracked vehicles</span><strong>{vehicles.length}</strong><small>Vehicles reporting position</small></div></article>
          <article className="metric-card"><span className="metric-icon amber">⌁</span><div><span className="metric-label">Active incidents</span><strong>{incidents.length}</strong><small>{highSeverity} high severity</small></div></article>
          <article className="metric-card"><span className="metric-icon violet">◉</span><div><span className="metric-label">Environmental risk</span><strong>{risk?.prediction?.score ?? "—"}<small className="metric-unit"> / 100</small></strong><small>{risk?.prediction?.level ?? "Awaiting assessment"} risk level</small></div></article>
          <article className="metric-card"><span className="metric-icon green">⌖</span><div><span className="metric-label">Road network</span><strong>{network?.features?.length ?? "—"}</strong><small>Mapped road segments</small></div></article>
        </section>

        <section className="content-grid">
          <div className="map-card">
            <div className="card-heading map-heading"><div><p className="eyebrow">LIVE MAP</p><h2>Route and fleet map</h2></div>
              <div className="route-switch" role="group" aria-label="Select route">
                <button className={selectedRoute === "normal" ? "selected primary" : ""} onClick={() => setSelectedRoute("normal")} type="button"><i className="route-key primary-key" />Primary</button>
                <button className={selectedRoute === "safer" ? "selected safer" : ""} onClick={() => setSelectedRoute("safer")} type="button"><i className="route-key safer-key" />Risk-weighted</button>
              </div>
            </div>
            <div className="map-frame"><MapView network={network} routes={routes} vehicles={vehicles} incidents={incidents} selectedRoute={selectedRoute} onSelectRoute={setSelectedRoute} /></div>
            <div className="map-footer"><span><i className="legend-line road-legend" />Road network</span><span><i className="legend-line primary-legend" />Primary route</span><span><i className="legend-line safer-legend" />Risk-weighted route</span><span><i className="legend-dot incident-legend" />Incident</span></div>
          </div>

          <aside className="side-column">
            <AlertPanel risk={risk} weather={weather} routes={routes} />
            <div className="panel-card live-source-panel"><div className="card-heading"><div><p className="eyebrow">EXTERNAL FEEDS</p><h2>Live source status</h2></div></div>
              {liveSourcesError ? <p className="empty-state">{liveSourcesError}</p> : !liveSources ? <p className="empty-state">Checking configured providers…</p> : <div className="source-status-list">{Object.entries(liveSources).map(([key, source]) => <div className="source-status-row" key={key}><span>{({open_meteo:"Open-Meteo",open_weather:"OpenWeather",nasa_eonet:"NASA EONET",nasa_firms:"NASA FIRMS",open_topography:"OpenTopography",open_street_map:"OpenStreetMap",isro_mosdac:"MOSDAC",copernicus_glofas:"GloFAS",mapillary:"Mapillary"})[key] ?? key}</span><span className={`source-status ${String(source.status || "UNKNOWN").toLowerCase()}`}>{source.status || "UNKNOWN"}</span></div>)}</div>}
              <p className="source-status-note">Only LIVE CONNECTED feeds contain an upstream observation. Other providers need credentials or product setup.</p>
            </div>
            <div className="panel-card incident-create"><div className="card-heading"><div><p className="eyebrow">FIELD REPORT</p><h2>Report an incident</h2></div><span className="form-icon">＋</span></div>
              <IncidentForm onIncidentAdded={handleIncidentAdded} /></div>
          </aside>
        </section>

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
