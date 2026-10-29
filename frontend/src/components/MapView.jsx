import {
  MapContainer,
  TileLayer,
  Polyline,
  Marker,
  Popup,
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


function MapView({ network, routes, vehicles }) {

  // Debug vehicle data
  console.log("VEHICLES:", vehicles);
  console.log("VEHICLES TYPE:", typeof vehicles);
  console.log("IS ARRAY:", Array.isArray(vehicles));


  const center = [25.42, 91.79];


  // Convert GeoJSON [longitude, latitude]
  // into Leaflet [latitude, longitude]
  const convertCoordinates = (coordinates = []) => {

    if (!Array.isArray(coordinates)) {
      return [];
    }

    return coordinates.map(([lon, lat]) => [lat, lon]);
  };


  // Primary route
  const primaryRoute = convertCoordinates(
    routes?.normal?.coordinates
  );


  // Safer AI route
  const saferRoute = convertCoordinates(
    routes?.safer?.coordinates
  );


  // Make sure vehicles is always an array
  const vehicleList = Array.isArray(vehicles)
    ? vehicles
    : [];


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


        {/* -------------------------------- */}
        {/* ROAD NETWORK */}
        {/* -------------------------------- */}

        {network?.features?.map(
          (feature, index) => {

            const coordinates =
              feature.geometry?.coordinates;

            if (!coordinates) {
              return null;
            }

            return (

              <Polyline
                key={`network-${index}`}
                positions={convertCoordinates(
                  coordinates
                )}
                pathOptions={{
                  weight: 3,
                  opacity: 0.35,
                }}
              />

            );
          }
        )}


        {/* -------------------------------- */}
        {/* PRIMARY ROUTE */}
        {/* -------------------------------- */}

        {primaryRoute.length > 1 && (

          <Polyline
            positions={primaryRoute}
            pathOptions={{
              weight: 7,
              opacity: 0.9,
            }}
          >

            <Popup>

              <strong>
                Primary Route
              </strong>

              <br />

              Risk Score:{" "}
              {routes?.normal?.risk_score ?? "N/A"}

              <br />

              Distance:{" "}
              {routes?.normal?.distance_km ?? "N/A"} km

            </Popup>

          </Polyline>

        )}


        {/* -------------------------------- */}
        {/* AI SAFER ROUTE */}
        {/* -------------------------------- */}

        {saferRoute.length > 1 && (

          <Polyline
            positions={saferRoute}
            pathOptions={{
              weight: 7,
              opacity: 0.95,
              dashArray: "10 8",
            }}
          >

            <Popup>

              <strong>
                AI Recommended Safer Route
              </strong>

              <br />

              Risk Score:{" "}
              {routes?.safer?.risk_score ?? "N/A"}

              <br />

              Distance:{" "}
              {routes?.safer?.distance_km ?? "N/A"} km

            </Popup>

          </Polyline>

        )}


        {/* -------------------------------- */}
        {/* VEHICLES */}
        {/* -------------------------------- */}

        {vehicleList.map((vehicle, index) => (

          <Marker
            key={vehicle.id ?? `vehicle-${index}`}
            position={[
              vehicle.lat,
              vehicle.lon,
            ]}
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

        ))}


      </MapContainer>

    </div>

  );
}


export default MapView;