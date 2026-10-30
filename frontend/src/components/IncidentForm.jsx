import { useState } from "react";

export default function IncidentForm({ onIncidentAdded }) {
  const [type, setType] = useState("ROAD_BLOCK");
  const [severity, setSeverity] = useState("MEDIUM");
  const [description, setDescription] = useState("");
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState({ text: "", error: false });

  async function submit(event) {
    event.preventDefault();
    setFeedback({ text: "", error: false });
    if ((lat === "") !== (lon === "")) {
      setFeedback({ text: "Enter both coordinates, or leave both blank.", error: true });
      return;
    }
    setBusy(true);
    try {
      const body = { type, severity, description: description.trim() };
      if (lat !== "" && lon !== "") { body.lat = Number(lat); body.lon = Number(lon); }
      const response = await fetch(`${import.meta.env.VITE_API_URL ?? ""}/api/incidents`, {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Incident could not be saved.");
      onIncidentAdded?.(data.incident);
      setDescription(""); setLat(""); setLon("");
      setFeedback({ text: "Incident saved successfully.", error: false });
    } catch (error) {
      setFeedback({ text: error.message || "Could not connect to the server.", error: true });
    } finally { setBusy(false); }
  }

  return (
    <form className="incident-form" onSubmit={submit}>
      <label>Incident type<select value={type} onChange={(event) => setType(event.target.value)}><option value="ROAD_BLOCK">Road blockage</option><option value="LANDSLIDE">Landslide</option><option value="FLOOD">Flooding</option><option value="ACCIDENT">Road accident</option><option value="LOW_VISIBILITY">Low visibility</option><option value="OTHER">Other</option></select></label>
      <label>Severity<select value={severity} onChange={(event) => setSeverity(event.target.value)}><option value="HIGH">High</option><option value="MEDIUM">Medium</option><option value="LOW">Low</option></select></label>
      <label>Description<textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Describe what happened and any impact on the road…" required maxLength={2000} /></label>
      <div className="coordinate-fields"><label>Latitude <span>(optional)</span><input type="number" min="-90" max="90" step="any" value={lat} onChange={(event) => setLat(event.target.value)} placeholder="e.g. 27.33" /></label><label>Longitude <span>(optional)</span><input type="number" min="-180" max="180" step="any" value={lon} onChange={(event) => setLon(event.target.value)} placeholder="e.g. 88.61" /></label></div>
      <p className="form-hint">Add coordinates to place the incident on the map.</p>
      <button className="primary-button" type="submit" disabled={busy}>{busy ? "Saving incident…" : "Submit incident report"}</button>
      {feedback.text && <p className={`form-feedback ${feedback.error ? "error" : "success"}`} role="status">{feedback.text}</p>}
    </form>
  );
}
