import { useMemo, useState } from "react";

export default function NotificationPanel({ incidents = [] }) {
  const [read, setRead] = useState(() => new Set());
  const items = useMemo(() => [...incidents].sort((a, b) => new Date(b.timestamp || 0) - new Date(a.timestamp || 0)), [incidents]);
  function markRead(id) { setRead((current) => new Set([...current, id])); }
  if (!items.length) return <p className="empty-state">No incident reports yet. New reports will appear here.</p>;
  return <div className="notification-list">{items.slice(0, 8).map((incident, index) => {
    const id = incident.id ?? index;
    const severity = String(incident.severity || "unknown").toLowerCase();
    return <article className={`incident-row ${read.has(id) ? "is-read" : ""}`} key={id}>
      <span className={`incident-severity ${severity}`} />
      <div className="incident-row-copy"><div className="incident-row-title"><strong>{String(incident.type || "Incident").replaceAll("_", " ")}</strong><span className={`severity-label ${severity}`}>{incident.severity || "Unknown"}</span></div>
        <p>{incident.description || "No description provided."}</p><small>{incident.timestamp ? new Date(incident.timestamp).toLocaleString() : "Time unavailable"}{incident.source ? ` · ${incident.source.replaceAll("_", " ")}` : ""}</small>
      </div>
      {!read.has(id) && <button className="text-button" type="button" onClick={() => markRead(id)}>Mark read</button>}
    </article>;
  })}</div>;
}
