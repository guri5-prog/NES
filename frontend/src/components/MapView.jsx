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
        {primary.length > 1 && <Polyline positions={primary} eventHandlers={{ click: () => onSelectRoute?.("normal") }} pathOptions={{ color: selectedRoute === "normal" ? "#2563eb" : "#94a3b8", weight: selectedRoute === "normal" ? 7 : 4, opacity: selectedRoute === "normal" ? 0.96 : 0.58, lineCap: "round", lineJoin: "round" }}><Popup><strong>Primary route</strong><br />Distance: {routes?.normal?.distance_km ?? "—"} km{routes?.normal?.duration_minutes != null && <><br />Estimated time: {routes.normal.duration_minutes} min</>}</Popup></Polyline>}
        {safer.length > 1 && <Polyline positions={safer} eventHandlers={{ click: () => onSelectRoute?.("safer") }} pathOptions={{ color: selectedRoute === "safer" ? "#15945a" : "#86b99b", weight: selectedRoute === "safer" ? 7 : 4, opacity: selectedRoute === "safer" ? 0.96 : 0.62, dashArray: "8 7", lineCap: "round", lineJoin: "round" }}><Popup><strong>Alternative route</strong><br />Distance: {routes?.safer?.distance_km ?? "—"} km{routes?.safer?.duration_minutes != null && <><br />Estimated time: {routes.safer.duration_minutes} min</>}</Popup></Polyline>}
        {activeRoute.length > 1 && <><CircleMarker center={activeRoute[0]} radius={7} pathOptions={{ color: "#fff", weight: 2, fillColor: "#16a34a", fillOpacity: 1 }}><Popup>Route start</Popup></CircleMarker><CircleMarker center={activeRoute[activeRoute.length - 1]} radius={7} pathOptions={{ color: "#fff", weight: 2, fillColor: "#2563eb", fillOpacity: 1 }}><Popup>Route destination</Popup></CircleMarker></>}
        {vehicles.map((vehicle, index) => {
          const lat = Number(vehicle.lat), lon = Number(vehicle.lon);
          if (vehicle.lat == null || vehicle.lon == null || !Number.isFinite(lat) || !Number.isFinite(lon)) return null;
          return <Marker key={vehicle.id ?? index} position={[lat, lon]} icon={vehicleIcon}><Popup><strong>{vehicle.id || "Vehicle"}</strong><br />{vehicle.driver || "Driver not specified"}<br />{vehicle.cargo || "Cargo not specified"}<br />Speed: {vehicle.speed ?? "—"} km/h<br />Status: {vehicle.status || "Unknown"}</Popup></Marker>;
        })}
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
