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
  const costFormula = routes?.cost_function;

  // Active risk factors from prediction or routes
  const factors = prediction?.risk_factors || primary?.risk_factors || [];

  return (
    <section className="panel-card risk-panel">
      <div className="card-heading">
        <div>
          <p className="eyebrow">CONDITIONS & AI INFERENCE</p>
          <h2>Risk assessment</h2>
        </div>
        <span className={`risk-chip ${level}`}>
          {level === "unknown" ? "Pending" : `${level} risk`}
        </span>
      </div>

      <div className={`risk-summary ${level}`}>
        <div>
          <span>Heuristic disruption indicator</span>
          <strong>
            {prediction?.probability != null
              ? `${(prediction.probability * 100).toFixed(0)}`
              : Number.isFinite(score)
              ? `${score.toFixed(0)}`
              : "—"}
            <small> / 100</small>
          </strong>
        </div>
        <div className="risk-meter">
          <span
            style={{
              width: `${
                prediction?.probability != null
                  ? Math.max(0, Math.min(prediction.probability * 100, 100))
                  : Number.isFinite(score)
                  ? Math.max(0, Math.min(score, 100))
                  : 0
              }%`,
            }}
          />
        </div>
        <small>
          {prediction?.level ? `${prediction.level} hazard state` : "Awaiting AI inference"}
        </small>
      </div>

      {factors.length > 0 && (
        <div style={{ marginTop: "11px", marginBottom: "4px" }}>
          <p className="eyebrow" style={{ marginBottom: "5px" }}>PRIMARY RISK DRIVERS</p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "5px" }}>
            {factors.slice(0, 3).map((factor, idx) => (
              <span
                key={idx}
                style={{
                  fontSize: "9px",
                  padding: "3px 7px",
                  background: "#f1f4f9",
                  borderRadius: "6px",
                  color: "#475569",
                  fontWeight: "600",
                }}
              >
                ⚠ {factor}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="route-risk-grid">
        <div>
          <span>Primary Route (α=1, β=0)</span>
          <strong>{primary?.distance_km ?? "—"}<small> km</small></strong>
          <small>
            Risk index: {primary?.risk_indicator ?? primary?.risk_score ?? "—"}/100 · Cost: {primary?.total_cost ?? primary?.distance_km ?? "—"}
          </small>
        </div>
        <div>
          <span>Risk-weighted route (α=1, β=25)</span>
          <strong>{safer?.distance_km ?? "—"}<small> km</small></strong>
          <small>
            Risk index: {safer?.risk_indicator ?? safer?.risk_score ?? "—"}/100 · Cost: {safer?.total_cost ?? "—"}
          </small>
        </div>
      </div>

      {recommendation && (
        <div className={`recommendation ${recommendation.recommended ? "recommended" : ""}`}>
          <span className="recommendation-icon">
            {recommendation.recommended ? "!" : "✓"}
          </span>
          <p>
            <strong>
              {recommendation.recommended
                ? "Risk-weighted alternative has a lower indicator"
                : "Primary corridor available"}
            </strong>
            <small>{recommendation.reason}</small>
          </p>
        </div>
      )}

      <div className="weather-block">
        <div className="weather-title">
          <span>Live Environmental Feed</span>
          <span className="weather-condition">
            {weather?.source ? `${weather.source}` : weather?.condition || "Live"}
          </span>
        </div>
        <div className="weather-values">
          <div>
            <strong>{weather?.rainfall_mm ?? "—"}<small> mm</small></strong>
            <span>Rainfall</span>
          </div>
          <div>
            <strong>{weather?.visibility_km ?? "—"}<small> km</small></strong>
            <span>Visibility</span>
          </div>
          <div>
            <strong>{weather?.temperature_c ?? "—"}<small>°C</small></strong>
            <span>Temperature</span>
          </div>
        </div>
      </div>
    </section>
  );
}
