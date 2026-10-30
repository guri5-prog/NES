const labels = { LIVE_CONNECTED: "Live", UNAVAILABLE: "Unavailable", NOT_CONFIGURED: "Needs setup", NO_ROUTE: "No route" };

export default function RouteConditionsPanel({ routes, selectedRoute = "normal" }) {
  const conditions = routes?.route_conditions?.[selectedRoute];
  const points = conditions?.points ?? [];
  return (
    <section className="panel-card route-conditions-panel">
      <div className="card-heading"><div><p className="eyebrow">SELECTED CORRIDOR</p><h2>Weather and visibility</h2></div>
        <span className={`source-status ${(conditions?.status || "unknown").toLowerCase()}`}>{labels[conditions?.status] || conditions?.status || "Waiting"}</span>
      </div>
      {points.length ? <div className="route-weather-grid">{points.map((point) => <article className="route-weather-point" key={`${point.position}-${point.lat}-${point.lon}`}>
        <strong>{point.position}</strong><small>{point.lat.toFixed(3)}, {point.lon.toFixed(3)}</small>
        <div><span>Rain</span><b>{point.rainfall_mm == null ? "—" : `${point.rainfall_mm} mm`}</b></div>
        <div><span>Visibility</span><b>{point.visibility_km == null ? "—" : `${point.visibility_km} km`}</b></div>
        <div><span>Temperature</span><b>{point.temperature_c == null ? "—" : `${point.temperature_c} °C`}</b></div>
        <div><span>Rain, 24 hours</span><b>{point.rainfall_24h_mm == null ? "—" : `${point.rainfall_24h_mm} mm`}</b></div>
        <small>OpenWeather: {labels[point.visibility_status] || point.visibility_status || "unknown"}</small>
      </article>)}</div> : <p className="empty-state">Search for two places and calculate a route to load corridor conditions.</p>}
      <p className="source-status-note">Weather is sampled at the chosen route’s start, midpoint, and destination. Conditions may vary between sample points.</p>
    </section>
  );
}
