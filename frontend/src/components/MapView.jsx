import {
  MapContainer,
  TileLayer,
  Polyline,
  Marker,
  Popup,
  CircleMarker,
} from "react-leaflet";

import L from "leaflet";
import "leaflet/dist/leaflet.css";

import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";

const vehicleIcon = new L.Icon({
  iconUrl: markerIcon,
  iconRetinaUrl: markerIcon2x,
  shadowUrl: markerShadow,
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41],
});

function MapView({
  network,
  routes,
  vehicles,
  incidents = [],
  selectedRoute = "normal",
  onSelectRoute,
  selectedIncidentType = "ROAD_BLOCK",
}) {
  const center = [25.42, 91.79];

  // Convert GeoJSON [longitude, latitude]
  // into Leaflet [latitude, longitude].
  const convertCoordinates = (coordinates = []) => {
    if (!Array.isArray(coordinates)) {
      return [];
    }

    return coordinates
      .filter(
        (point) =>
          Array.isArray(point) &&
          point.length >= 2 &&
          Number.isFinite(Number(point[0])) &&
          Number.isFinite(Number(point[1]))
      )
      .map(([lon, lat]) => [Number(lat), Number(lon)]);
  };

  // Hardcoded route coordinates for frontend testing.
  // Format: [latitude, longitude]

  const testPrimaryRoute = [
    [25.3650, 91.7350],
    [25.3720, 91.7420],
    [25.3800, 91.7500],
    [25.3900, 91.7580],
    [25.4000, 91.7680],
    [25.4100, 91.7780],
    [25.4200, 91.7900],
  ];

  const testSaferRoute = [
    [25.3650, 91.7350],
    [25.3700, 91.7480],
    [25.3800, 91.7600],
    [25.3920, 91.7700],
    [25.4050, 91.7800],
    [25.4200, 91.7900],
  ];

  
  // uncomment for real coordinates
  // Primary route coordinates.
  // const primaryRoute = convertCoordinates(
  //   routes?.normal?.coordinates
  // );

  // // AI safer route coordinates.
  // const saferRoute = convertCoordinates(
  //   routes?.safer?.coordinates
  // );

  // Use hardcoded coordinates temporarily for testing.
// Backend fetching remains unchanged in App.jsx.

// --------------------------------
// ROUTES FOR EACH INCIDENT TYPE
// --------------------------------

// ROAD BLOCK routes: keep your existing coordinates
const roadblockPrimaryRoute = testPrimaryRoute;
const roadblockSaferRoute = testSaferRoute;

// LANDSLIDE primary route
const landslidePrimaryRoute = [
  [25.3450, 91.7050],
  [25.3500, 91.6950],
  [25.3600, 91.6880],
  [25.3750, 91.6920],
  [25.3900, 91.7150],
  [25.4050, 91.7500],
  [25.4200, 91.7900],
];

const landslideSaferRoute = [
  [25.3450, 91.7050],
  [25.3520, 91.7120],
  [25.3650, 91.7200],
  [25.3820, 91.7350],
  [25.4000, 91.7600],
  [25.4200, 91.7900],
];

// Store both routes for each incident type
const routeSets = {
  ROAD_BLOCK: {
    normal: roadblockPrimaryRoute,
    safer: roadblockSaferRoute,
  },

  LANDSLIDE: {
    normal: landslidePrimaryRoute,
    safer: landslideSaferRoute,
  },
};

// Select the route pair based on the incident dropdown
const activeRoutes =
  routeSets[selectedIncidentType] ?? routeSets.ROAD_BLOCK;

// Keep these variable names because the rendering code uses them
const primaryRoute = activeRoutes.normal;
const saferRoute = activeRoutes.safer;

  // Ensure vehicles is always an array.
  const vehicleList = Array.isArray(vehicles)
    ? vehicles
    : [];

  // Route styling based on selection.
  const getRouteStyle = (routeName) => {
    const isSelected = selectedRoute === routeName;

    const color =
      routeName === "safer" ? "#16a34a" : "#1677ff";

    return {
      isSelected,
      color: isSelected ? color : "#9ca3af",
      weight: isSelected ? 7 : 4,
      opacity: isSelected ? 1 : 0.65,
    };
  };

  const primaryStyle = getRouteStyle("normal");
  const saferStyle = getRouteStyle("safer");

  // --------------------------------
// MARKERS FOR EACH INCIDENT ROUTE
// --------------------------------

// --------------------------------
// START AND DESTINATION MARKERS
// --------------------------------

const markerSets = {
  ROAD_BLOCK: {
    normal: [
      {
        position: roadblockPrimaryRoute[0],
        label: "Start",
      },
      {
        position: roadblockPrimaryRoute[roadblockPrimaryRoute.length - 1],
        label: "Destination",
      },
    ],

    safer: [
      {
        position: roadblockSaferRoute[0],
        label: "Start",
      },
      {
        position: roadblockSaferRoute[roadblockSaferRoute.length - 1],
        label: "Destination",
      },
    ],
  },

  LANDSLIDE: {
    normal: [
      {
        position: landslidePrimaryRoute[0],
        label: "Start",
      },
      {
        position: landslidePrimaryRoute[landslidePrimaryRoute.length - 1],
        label: "Destination",
      },
    ],

    safer: [
      {
        position: landslideSaferRoute[0],
        label: "Start",
      },
      {
        position: landslideSaferRoute[landslideSaferRoute.length - 1],
        label: "Destination",
      },
    ],
  },
};

// Markers for the selected incident and route
const activeMarkers =
  markerSets[selectedIncidentType]?.[selectedRoute] ??
  markerSets.ROAD_BLOCK.normal;

  return (
    <div className="map-container">
      <MapContainer
        center={center}
        zoom={10}
        scrollWheelZoom={true}
        style={{
          width: "100%",
          height: "100%",
        }}
      >
        <TileLayer
          attribution="&copy; OpenStreetMap contributors"
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {/* ROAD NETWORK */}
        {network?.features?.map((feature, index) => {
          const coordinates = feature.geometry?.coordinates;

          if (
            !coordinates ||
            feature.geometry?.type !== "LineString"
          ) {
            return null;
          }

          const positions = convertCoordinates(coordinates);

          if (positions.length < 2) {
            return null;
          }

          return (
            <Polyline
              key={`network-${index}`}
              positions={positions}
              pathOptions={{
                color: "#64748b",
                weight: 3,
                opacity: 0.35,
              }}
            />
          );
        })}

        {/* PRIMARY ROUTE */}
        {primaryRoute.length > 1 && (
          <>
            {/* White outline makes the route stand out. */}
            <Polyline
              positions={primaryRoute}
              pathOptions={{
                color: "#ffffff",
                weight: primaryStyle.isSelected ? 11 : 6,
                opacity: primaryStyle.isSelected ? 0.95 : 0.45,
                lineCap: "round",
                lineJoin: "round",
              }}
              interactive={false}
            />

            <Polyline
              positions={primaryRoute}
              eventHandlers={{click: () => onSelectRoute?.("normal"),}}
              pathOptions={{
                color: primaryStyle.color,
                weight: primaryStyle.weight,
                opacity: primaryStyle.opacity,
                lineCap: "round",
                lineJoin: "round",
              }}
            >
              <Popup>
                <strong>
                  {primaryStyle.isSelected
                    ? "✓ Selected Primary Route"
                    : "Alternative Primary Route"}
                </strong>

                <br />

                Risk Score:{" "}
                {routes?.normal?.risk_score ?? "N/A"}

                <br />

                Distance:{" "}
                {routes?.normal?.distance_km ?? "N/A"} km
              </Popup>
            </Polyline>
          </>
        )}

        {/* AI SAFER ROUTE */}
        {saferRoute.length > 1 && (
          <>
            {/* White outline beneath the safer route. */}
            <Polyline
              positions={saferRoute}
              pathOptions={{
                color: "#ffffff",
                weight: saferStyle.isSelected ? 11 : 6,
                opacity: saferStyle.isSelected ? 0.95 : 0.45,
                lineCap: "round",
                lineJoin: "round",
              }}
              interactive={false}
            />

            <Polyline
              positions={saferRoute}
              eventHandlers={{click: () => onSelectRoute?.("safer"),}}
              pathOptions={{
                color: saferStyle.color,
                weight: saferStyle.weight,
                opacity: saferStyle.opacity,
                lineCap: "round",
                lineJoin: "round",
              }}
            >
              <Popup>
                <strong>
                  {saferStyle.isSelected
                    ? "✓ Selected AI Safer Route"
                    : "Alternative Safer Route"}
                </strong>

                <br />

                Risk Score:{" "}
                {routes?.safer?.risk_score ?? "N/A"}

                <br />

                Distance:{" "}
                {routes?.safer?.distance_km ?? "N/A"} km
              </Popup>
            </Polyline>
          </>
        )}

                {/* ROUTE WAYPOINT MARKERS */}
        {activeMarkers.map((marker, index) => {
          const isIncident =
            marker.label === "Road Block" ||
            marker.label === "Landslide";

          const isStart = marker.label === "Start";
          const isDestination = marker.label === "Destination";

          const markerColor = isIncident
            ? "#dc2626"
            : isStart
              ? "#16a34a"
              : isDestination
                ? "#1677ff"
                : "#7c3aed";

          return (
            <CircleMarker
              key={`waypoint-${selectedIncidentType}-${selectedRoute}-${index}`}
              center={marker.position}
              radius={isIncident ? 10 : 7}
              pathOptions={{
                color: "#ffffff",
                weight: 2,
                fillColor: markerColor,
                fillOpacity: 1,
              }}
            >
              <Popup>
                <strong>{marker.label}</strong>
                <br />
                Incident: {selectedIncidentType.replace("_", " ")}
                <br />
                Route: {selectedRoute === "normal" ? "Primary" : "AI Safer"}
              </Popup>
            </CircleMarker>
          );
        })}

        {/* VEHICLES */}
        {vehicleList.map((vehicle, index) => {
          const lat = Number(vehicle.lat);
          const lon = Number(vehicle.lon);

          if (
            vehicle.lat == null ||
            vehicle.lon == null ||
            !Number.isFinite(lat) ||
            !Number.isFinite(lon)
          ) {
            return null;
          }

          return (
            <Marker
              key={vehicle.id ?? `vehicle-${index}`}
              position={[lat, lon]}
              icon={vehicleIcon}
            >
              <Popup>
                <strong>
                  {vehicle.id ?? "Unknown Vehicle"}
                </strong>

                <br />

                Cargo: {vehicle.cargo ?? "N/A"}

                <br />

                Speed: {vehicle.speed ?? "N/A"} km/h

                <br />

                Status: {vehicle.status ?? "Unknown"}
              </Popup>
            </Marker>
          );
        })}

        {/* BLOCKED ROAD INCIDENTS */}
        {incidents
          .filter((incident) =>
            [
              "ROAD_BLOCK",
              "BLOCKED_ROAD",
              "ROAD_BLOCKED",
            ].includes(
              String(incident.type ?? "").toUpperCase()
            )
          )
          .filter(
            (incident) =>
              incident.lat != null &&
              incident.lon != null &&
              Number.isFinite(Number(incident.lat)) &&
              Number.isFinite(Number(incident.lon))
          )
          .map((incident, index) => (
            <CircleMarker
              key={`blocked-${incident.id ?? index}`}
              center={[
                Number(incident.lat),
                Number(incident.lon),
              ]}
              radius={9}
              pathOptions={{
                color: "#dc2626",
                fillColor: "#ef4444",
                fillOpacity: 0.9,
                weight: 2,
              }}
            >
              <Popup>
                <strong>Blocked Road Alert</strong>

                <br />

                {incident.description || "Road blockage reported"}

                <br />

                Severity: {incident.severity ?? "UNKNOWN"}
              </Popup>
            </CircleMarker>
          ))}
      </MapContainer>
    </div>
  );
}

export default MapView;