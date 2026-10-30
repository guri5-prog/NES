function RouteOption({ title, route, selected, onSelect, disabled }) {
  return (
    <button className={`route-option-card ${selected ? "selected" : ""}`} type="button" onClick={onSelect} disabled={disabled}>
      <span className="route-option-title">{title}</span>
      {route?.coordinates?.length > 1 ? <>
        <strong>{route.distance_km ?? "—"}<small> km</small></strong>
        <span className="route-option-meta">{route.duration_minutes != null ? `About ${route.duration_minutes} min` : "Estimated distance"}</span>
        {route.risk_score != null && <span className={`route-option-risk ${String(route.risk_level || "unknown").toLowerCase()}`}>Risk {Number(route.risk_score).toFixed(1)}/100 · {String(route.risk_level || "unknown").toLowerCase()}</span>}
      </> : <span className="route-option-meta">No route available</span>}
    </button>
  );
}

export default function AlertPanel({ routes, selectedRoute, onSelectRoute }) {
  const primary = routes?.normal;
  const alternative = routes?.safer;
  const hasAlternative = routes?.has_alternative ?? Boolean(alternative?.coordinates?.length > 1);
  const selected = selectedRoute === "safer" ? alternative : primary;
  const score = Number(selected?.risk_score);
  const hasScore = selected?.risk_score != null && Number.isFinite(score);
  const riskLevel = String(selected?.risk_level || "unknown").toLowerCase();
  const watchSections = [...(selected?.segments ?? [])]
    .filter((segment) => Number(segment.risk_indicator) > 0)
    .sort((a, b) => Number(b.risk_indicator) - Number(a.risk_indicator)
      || Number(b.nearby_incident_count ?? 0) - Number(a.nearby_incident_count ?? 0))
    .slice(0, 3);

  return (
    <section className="panel-card route-options-panel">
      <div className="card-heading"><div><p className="eyebrow">AVAILABLE ROUTES</p><h2>Choose a route</h2></div></div>
      <div className="route-options-grid">
        <RouteOption title="Primary route" route={primary} selected={selectedRoute === "normal"} onSelect={() => onSelectRoute("normal")} />
        <RouteOption title="Alternative route" route={alternative} selected={selectedRoute === "safer"} onSelect={() => onSelectRoute("safer")} disabled={!hasAlternative} />
      </div>
      {!hasAlternative && <p className="source-status-note">No distinct alternative was returned for these locations.</p>}
      <div className={`route-risk-summary ${riskLevel}`}>
        <div className="route-risk-heading"><div><span className="route-option-title">{selectedRoute === "safer" ? "Alternative" : "Primary"} route risk</span><strong>{hasScore ? <>{score.toFixed(1)}<small> / 100</small></> : "—"}</strong></div>
          <span className={`risk-chip ${riskLevel}`}>{hasScore ? `${riskLevel} risk` : "Not assessed"}</span>
        </div>
        {hasScore && <div className="route-risk-meter" aria-label={`Route risk score ${score} out of 100`}><span style={{ width: `${Math.max(0, Math.min(score, 100))}%` }} /></div>}
        {selected?.risk_factors?.length > 0 ? <div className="route-risk-factors"><span>What affects this route</span><ul>{selected.risk_factors.slice(0, 4).map((factor) => <li key={factor}>{factor}</li>)}</ul></div>
          : <p className="source-status-note">{!selected ? "Search for a route to see its condition assessment." : selected.risk_data_status === "INSUFFICIENT_DATA" ? "Current weather and nearby incident data are not available for this route." : "No risk factors were reported for this route."}</p>}
        {watchSections.length > 0 && <div className="route-risk-factors"><span>Highest scoring road sections</span><ul>{watchSections.map((segment) => <li key={segment.segment_id}>{segment.road || "Route section"}: {Number(segment.risk_indicator).toFixed(0)}/100{segment.distance_km != null ? ` · ${segment.distance_km} km` : ""}{segment.nearby_incident_count ? ` · ${segment.nearby_incident_count} nearby report(s)` : ""}</li>)}</ul></div>}
        {hasScore && <p className="route-risk-disclaimer">Heuristic estimate from sampled weather and known incidents. Routes can share a score when those inputs are similar; this is not a disruption probability.</p>}
      </div>
    </section>
  );
}
