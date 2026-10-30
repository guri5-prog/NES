import { useEffect, useMemo } from "react";
import { CircleMarker, GeoJSON, ImageOverlay, MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";

const vehicleIcon = new L.Icon({ iconUrl: markerIcon, iconRetinaUrl: markerIcon2x, shadowUrl: markerShadow, iconSize: [25, 41], iconAnchor: [12, 41], popupAnchor: [1, -34], shadowSize: [41, 41] });

function FitNetwork({ network, routes }) {
  const map = useMap();
  useEffect(() => {
    const bounds = L.latLngBounds([]);
    for (const feature of network?.features ?? []) {
      const geometry = feature.geometry;
      const lines = geometry?.type === "LineString" ? [geometry.coordinates] : geometry?.type === "MultiLineString" ? geometry.coordinates : [];
      for (const line of lines) for (const [lon, lat] of line) if (Number.isFinite(lat) && Number.isFinite(lon)) bounds.extend([lat, lon]);
    }
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [24, 24], maxZoom: 13 });
    else {
      const points = [...(routes?.normal?.coordinates ?? []), ...(routes?.safer?.coordinates ?? [])];
      if (points.length) map.fitBounds(points.map(([lon, lat]) => [lat, lon]), { padding: [24, 24], maxZoom: 13 });
    }
  }, [map, network, routes]);
  return null;
}

function routePositions(route) {
  return (route?.coordinates ?? []).filter((point) => Array.isArray(point) && point.length >= 2 && Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1]))).map(([lon, lat]) => [Number(lat), Number(lon)]);
}

function riskColor(score, riskBand) {
  if (riskBand === "congested" || riskBand === "elevated") return "#dc2626";
  if (riskBand === "caution") return "#eab308";
  if (!Number.isFinite(score)) return "#2563eb";
  if (score >= 35) return "#dc2626";
  if (score >= 15) return "#eab308";
  return "#2563eb";
}

function riskLabel(score) {
  if (score >= 35) return "Elevated risk";
  if (score >= 15) return "Caution";
  return "Lower risk";
}

function routeRiskRuns(route) {
  const runs = [];
  const sectionData = route?.risk_sections ?? route?.segments ?? [];
  const path = routePositions(route);
  for (const [index, segment] of sectionData.entries()) {
    const positions = Array.isArray(segment.coordinates)
      ? routePositions({ coordinates: segment.coordinates })
      : path.slice(index, index + 2);
    if (positions.length < 2) continue;
    const score = Number(segment.max_risk_indicator ?? segment.risk_indicator);
    const color = riskColor(score, segment.risk_band);
    const previous = runs[runs.length - 1];
    const startsAtPreviousEnd = previous && Math.abs(previous.positions.at(-1)[0] - positions[0][0]) < 1e-7
      && Math.abs(previous.positions.at(-1)[1] - positions[0][1]) < 1e-7;
    if (previous && previous.color === color && startsAtPreviousEnd) {
      previous.positions.push(...positions.slice(1));
      previous.maxScore = Math.max(previous.maxScore, Number.isFinite(score) ? score : 0);
      previous.segmentCount += Number(segment.segment_count ?? 1);
    } else {
      runs.push({ positions, color, maxScore: Number.isFinite(score) ? score : 0, segmentCount: Number(segment.segment_count ?? 1) });
    }
  }
  return runs;
}

function pointAlongRoute(route, fraction) {
  if (route.length < 2) return route[0] ?? null;
  const lengths = route.slice(1).map((point, index) => {
    const [lat1, lon1] = route[index];
    const [lat2, lon2] = point;
    const radians = Math.PI / 180;
    const deltaLat = (lat2 - lat1) * radians;
    const deltaLon = (lon2 - lon1) * radians;
    const value = Math.sin(deltaLat / 2) ** 2 + Math.cos(lat1 * radians) * Math.cos(lat2 * radians) * Math.sin(deltaLon / 2) ** 2;
    return 6371 * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(Math.max(0, 1 - value)));
  });
  const target = lengths.reduce((sum, length) => sum + length, 0) * Math.max(0, Math.min(1, fraction));
  let traversed = 0;
  for (let index = 0; index < lengths.length; index += 1) {
    const length = lengths[index];
    if (traversed + length >= target) {
      const ratio = length ? (target - traversed) / length : 0;
      return [
        route[index][0] + (route[index + 1][0] - route[index][0]) * ratio,
        route[index][1] + (route[index + 1][1] - route[index][1]) * ratio,
      ];
    }
    traversed += length;
  }
  return route[route.length - 1];
}

function escapePopup(value) {
  return String(value ?? "Unknown").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
}

function formatEventDate(value) {
  if (value == null || value === "") return "Unknown";
  const date = new Date(typeof value === "number" ? value : value);
  return Number.isNaN(date.getTime()) ? escapePopup(value) : escapePopup(date.toLocaleDateString());
}

function MapView({ network, routes, vehicles = [], incidents = [], selectedRoute = "normal", onSelectRoute, landslideData, showCoolr = false, showLhasa = false }) {
  const primary = useMemo(() => routePositions(routes?.normal), [routes]);
  const safer = useMemo(() => routePositions(routes?.safer), [routes]);
  const activeRoute = selectedRoute === "safer" ? safer : primary;
  const primaryRiskRuns = useMemo(() => routeRiskRuns(routes?.normal), [routes]);
  const saferRiskRuns = useMemo(() => routeRiskRuns(routes?.safer), [routes]);
  const routeIsSelected = activeRoute.length > 1;
  const visibleVehicles = vehicles.flatMap((vehicle, index) => {
    if (routeIsSelected) {
      const position = pointAlongRoute(activeRoute, (index + 1) / (vehicles.length + 1));
      return position ? [{ vehicle, index, position, offsetKm: null, simulated: true }] : [];
    }
    const lat = Number(vehicle.lat), lon = Number(vehicle.lon);
    if (vehicle.lat == null || vehicle.lon == null || !Number.isFinite(lat) || !Number.isFinite(lon)) return [];
    return [{ vehicle, index, position: [lat, lon], offsetKm: null, simulated: false }];
  });

  function renderRoute(routeKey, runs, fallbackPositions, route, selected, color, inactiveColor) {
    if (runs.length) return <>
      {routeKey === "safer" && fallbackPositions.length > 1 && <Polyline key="alternative-route-underlay" positions={fallbackPositions} eventHandlers={{ click: () => onSelectRoute?.(routeKey) }} pathOptions={{ color: selected ? color : inactiveColor, weight: selected ? 9 : 7, opacity: selected ? 0.95 : 0.72, lineCap: "round", lineJoin: "round" }} />}
      {runs.map((run, index) => <Polyline
        key={`${routeKey}-risk-run-${index}`}
        positions={run.positions}
        eventHandlers={{ click: () => onSelectRoute?.(routeKey) }}
        pathOptions={{
          color: run.color,
          weight: selected ? 5 : 3,
          opacity: selected ? 0.98 : 0.8,
          dashArray: routeKey === "safer" ? "8 7" : undefined,
          lineCap: "round",
          lineJoin: "round",
        }}
      ><Popup><strong>{routeKey === "normal" ? "Primary" : "Alternative"} route · {riskLabel(run.maxScore)}</strong><br />Highest section score: {run.maxScore.toFixed(1)}/100<br />{run.segmentCount} road section(s)<br />Heuristic guidance only; check current conditions before travel.</Popup></Polyline>)}
    </>;
    if (fallbackPositions.length < 2) return null;
    return <Polyline positions={fallbackPositions} eventHandlers={{ click: () => onSelectRoute?.(routeKey) }} pathOptions={{ color: selected ? color : inactiveColor, weight: selected ? 7 : 4, opacity: selected ? 0.96 : 0.58, dashArray: routeKey === "safer" ? "8 7" : undefined, lineCap: "round", lineJoin: "round" }}><Popup><strong>{routeKey === "normal" ? "Primary route" : "Alternative route"}</strong><br />Distance: {route?.distance_km ?? "—"} km</Popup></Polyline>;
  }

  return (
    <div className="map-container">
      <MapContainer center={[27.35, 88.61]} zoom={9} scrollWheelZoom className="leaflet-map">
        <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        <FitNetwork network={network} routes={routes} />
        {showLhasa && landslideData?.lhasa?.image_url && landslideData?.lhasa?.bounds && <ImageOverlay
          url={landslideData.lhasa.image_url}
          bounds={landslideData.lhasa.bounds}
          opacity={0.48}
          zIndex={350}
          attribution="NASA GSFC LHASA"
        />}
        {showCoolr && landslideData?.layers?.polygons?.features?.length > 0 && <GeoJSON
          key={`coolr-polygons-${landslideData.timestamp ?? landslideData.cache}`}
          data={landslideData.layers.polygons}
          style={() => ({ color: "#b91c1c", weight: 2, fillColor: "#ef4444", fillOpacity: 0.3 })}
          onEachFeature={(feature, layer) => {
            const properties = feature.properties ?? {};
            layer.bindPopup(`<strong>NASA COOLR reported landslide area</strong><br/>Date: ${formatEventDate(properties.event_date)}<br/>Trigger: ${escapePopup(properties.landslide_trigger)}<br/>Source: ${escapePopup(properties.source_name)}`);
          }}
        />}
        {showCoolr && landslideData?.layers?.points?.features?.length > 0 && <GeoJSON
          key={`coolr-points-${landslideData.timestamp ?? landslideData.cache}`}
          data={landslideData.layers.points}
          pointToLayer={(_feature, latlng) => L.circleMarker(latlng, { radius: 6, color: "#fff", weight: 1.5, fillColor: "#dc2626", fillOpacity: 0.95 })}
          onEachFeature={(feature, layer) => {
            const properties = feature.properties ?? {};
            layer.bindPopup(`<strong>NASA COOLR reported landslide</strong><br/>Date: ${formatEventDate(properties.event_date)}<br/>Trigger: ${escapePopup(properties.landslide_trigger)}<br/>Size: ${escapePopup(properties.landslide_size)}<br/>Source: ${escapePopup(properties.source_name)}`);
          }}
        />}
        {network?.features?.length > 0 && <GeoJSON data={network} style={() => ({ color: "#8491a5", weight: 2, opacity: 0.45 })} />}
        {renderRoute("normal", primaryRiskRuns, primary, routes?.normal, selectedRoute === "normal", "#2563eb", "#94a3b8")}
        {renderRoute("safer", saferRiskRuns, safer, routes?.safer, selectedRoute === "safer", "#15945a", "#86b99b")}
        {activeRoute.length > 1 && <><CircleMarker center={activeRoute[0]} radius={7} pathOptions={{ color: "#fff", weight: 2, fillColor: "#16a34a", fillOpacity: 1 }}><Popup>Route start</Popup></CircleMarker><CircleMarker center={activeRoute[activeRoute.length - 1]} radius={7} pathOptions={{ color: "#fff", weight: 2, fillColor: "#2563eb", fillOpacity: 1 }}><Popup>Route destination</Popup></CircleMarker></>}
        {visibleVehicles.map(({ vehicle, index, position, offsetKm, simulated }) => <Marker key={vehicle.id ?? index} position={position} icon={vehicleIcon}>
          <Popup><strong>{simulated ? `Simulation vehicle ${index + 1}` : vehicle.id || "Vehicle"}</strong><br />{vehicle.driver || "Driver not specified"}<br />{vehicle.cargo || "Cargo not specified"}<br />Speed: {vehicle.speed ?? "—"} km/h<br />Status: {simulated ? "Simulated on selected route" : vehicle.status || "Unknown"}{offsetKm != null && <><br />Marker aligned to selected route; GPS offset {offsetKm.toFixed(1)} km.</>}</Popup>
        </Marker>)}
        {incidents.map((incident, index) => {
          const lat = Number(incident.lat), lon = Number(incident.lon);
          if (incident.lat == null || incident.lon == null || !Number.isFinite(lat) || !Number.isFinite(lon)) return null;
          const severity = String(incident.severity || "").toUpperCase();
          const color = severity === "HIGH" ? "#dc2626" : severity === "MEDIUM" ? "#ea8a13" : "#64748b";
          return <CircleMarker key={incident.id ?? index} center={[lat, lon]} radius={8} pathOptions={{ color: "#fff", weight: 2, fillColor: color, fillOpacity: 0.95 }}><Popup><strong>{String(incident.type || "Incident").replaceAll("_", " ")}</strong><br />{incident.description || "No description"}<br />Severity: {incident.severity || "Unknown"}{incident.timestamp && <><br />{new Date(incident.timestamp).toLocaleString()}</>}</Popup></CircleMarker>;
        })}
      </MapContainer>
      {!network?.features?.length && !primary.length && !safer.length && <div className="map-empty">Road network and routes are not available.</div>}
    </div>
  );
}

export default MapView;
