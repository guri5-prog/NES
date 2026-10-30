function levelFor(score) {
  if (!Number.isFinite(Number(score))) return "unknown";
  return Number(score) >= 70 ? "high" : Number(score) >= 40 ? "medium" : "low";
}

export default function AlertPanel({ risk, weather, routes }) {
  const prediction = risk?.prediction;
  const score = Number(prediction?.score);
  const level = String(prediction?.level || levelFor(score)).toLowerCase();
  const primary = routes?.normal;
  const safer = routes?.safer;
  const recommendation = routes?.recommendation;
  return (
    <section className="panel-card risk-panel">
      <div className="card-heading"><div><p className="eyebrow">CONDITIONS</p><h2>Risk assessment</h2></div><span className={`risk-chip ${level}`}>{level === "unknown" ? "Pending" : `${level} risk`}</span></div>
      <div className={`risk-summary ${level}`}><div><span>Environmental score</span><strong>{Number.isFinite(score) ? score.toFixed(0) : "—"}<small> / 100</small></strong></div><div className="risk-meter"><span style={{ width: `${Number.isFinite(score) ? Math.max(0, Math.min(score, 100)) : 0}%` }} /></div><small>{prediction?.level ? `${prediction.level} conditions` : "Waiting for risk data"}</small></div>
      <div className="route-risk-grid"><div><span>Primary route</span><strong>{primary?.risk_score ?? "—"}<small> risk</small></strong><small>{primary?.distance_km ?? "—"} km</small></div><div><span>Safer route</span><strong>{safer?.risk_score ?? "—"}<small> risk</small></strong><small>{safer?.distance_km ?? "—"} km</small></div></div>
      {recommendation && <div className={`recommendation ${recommendation.recommended ? "recommended" : ""}`}><span className="recommendation-icon">{recommendation.recommended ? "!" : "✓"}</span><p><strong>{recommendation.recommended ? "Alternate route recommended" : "Primary route available"}</strong><small>{recommendation.reason}</small></p></div>}
      <div className="weather-block"><div className="weather-title"><span>Current conditions</span><span className="weather-condition">{weather?.condition || "Weather unavailable"}</span></div><div className="weather-values"><div><strong>{weather?.rainfall_mm ?? "—"}<small> mm</small></strong><span>Rainfall</span></div><div><strong>{weather?.visibility_km ?? "—"}<small> km</small></strong><span>Visibility</span></div><div><strong>{weather?.temperature_c ?? "—"}<small>°</small></strong><span>Temperature</span></div></div></div>
    </section>
  );
}
