import { useEffect, useState } from "react";

import MapView from "./components/MapView";
import AlertPanel from "./components/AlertPanel";
import IncidentForm from "./components/IncidentForm";
import NotificationPanel from "./components/NotificationPanel";
import AuthPage from "./components/AuthPage";

import "./App.css";


const API_URL = "";


function App() {

  const [user, setUser] = useState(null);
  const [authChecking, setAuthChecking] = useState(true);

  const [network, setNetwork] = useState(null);

  const [routes, setRoutes] = useState(null);

  const [vehicles, setVehicles] = useState([]);

  const [weather, setWeather] = useState(null);

  const [risk, setRisk] = useState(null);

  const [incidents, setIncidents] = useState([]);

  const [backendOnline, setBackendOnline] = useState(false);

  const [selectedRoute, setSelectedRoute] = useState("normal");

  const [selectedIncidentType, setSelectedIncidentType] = useState("ROAD_BLOCK");
  


  async function fetchData() {

    try {

      const responses = await Promise.all([

        fetch(`${API_URL}/api/network`),

        fetch(`${API_URL}/api/routes`),

        fetch(`${API_URL}/api/vehicles`),

        fetch(`${API_URL}/api/weather`),

        fetch(`${API_URL}/api/risk`),

        fetch(`${API_URL}/api/incidents`),

      ]);


      // Check whether any API request failed
      for (const response of responses) {

        if (!response.ok) {

          if (response.status === 401) {
            setUser(null);
            return;
          }

          throw new Error(
            `API request failed: ${response.status}`
          );

        }

      }


      const [
        networkData,
        routesData,
        vehiclesData,
        weatherData,
        riskData,
        incidentsData,
      ] = await Promise.all(

        responses.map(
          (response) => response.json()
        )

      );


      // --------------------------------
      // DEBUG API RESPONSES
      // --------------------------------

      console.log(
        "API /vehicles response:",
        vehiclesData
      );

      console.log(
        "API /vehicles is array:",
        Array.isArray(vehiclesData)
      );

      console.log(
        "API /vehicles.vehicles is array:",
        Array.isArray(
          vehiclesData?.vehicles
        )
      );


      // --------------------------------
      // NETWORK
      // --------------------------------

      setNetwork(networkData);


      // --------------------------------
      // ROUTES
      // --------------------------------

      setRoutes(routesData);


      // --------------------------------
      // VEHICLES
      // --------------------------------

      let vehicleList = [];

      if (Array.isArray(vehiclesData)) {

        // Backend returned:
        // [ {...}, {...} ]

        vehicleList = vehiclesData;

      } else if (
        Array.isArray(vehiclesData?.vehicles)
      ) {

        // Backend returned:
        // { "vehicles": [ {...}, {...} ] }

        vehicleList =
          vehiclesData.vehicles;

      }


      setVehicles(vehicleList);


      // --------------------------------
      // WEATHER
      // --------------------------------

      setWeather(weatherData);


      // --------------------------------
      // RISK
      // --------------------------------

      setRisk(riskData);


      // --------------------------------
      // INCIDENTS
      // --------------------------------

      const incidentList =
        Array.isArray(incidentsData)
          ? incidentsData
          : Array.isArray(
              incidentsData?.incidents
            )
            ? incidentsData.incidents
            : [];


      setIncidents(incidentList);


      // --------------------------------
      // BACKEND STATUS
      // --------------------------------

      setBackendOnline(true);

    } catch (error) {

      console.error(
        "Backend connection failed:",
        error
      );

      setBackendOnline(false);

    }

  }


  useEffect(() => {
    fetch(`${API_URL}/api/auth/session`, { credentials: "include" })
      .then(async (response) => {
        if (!response.ok) return null;
        return response.json();
      })
      .then((data) => setUser(data?.user || null))
      .catch(() => setUser(null))
      .finally(() => setAuthChecking(false));
  }, []);


  useEffect(() => {

    if (!user) return undefined;

    fetchData();


    const interval = setInterval(
      fetchData,
      5000
    );


    return () => {

      clearInterval(interval);

    };

  }, [user]);


  async function handleLogout() {
    try {
      await fetch(`${API_URL}/api/auth/logout`, { method: "POST", credentials: "include" });
    } finally {
      setUser(null);
    }
  }


  // --------------------------------
  // INCIDENT ADDED
  // --------------------------------

  function handleIncidentAdded(
    incident
  ) {

    setIncidents(
      (current) => [
        ...current,
        incident,
      ]
    );

  }


  if (authChecking) {
    return <main className="auth-page"><p className="auth-loading">Loading your session...</p></main>;
  }

  if (!user) {
    return <AuthPage onAuthenticated={setUser} />;
  }

  return (

    <div className="app">


      {/* -------------------------------- */}
      {/* HEADER */}
      {/* -------------------------------- */}

      <header className="header">

        <div>

          <h1>
            AI Smart Logistics
          </h1>

          <p>
            Risk-Aware Route Intelligence
          </p>

        </div>


        <div className="header-actions">
        <div className="system-status">

          <span
            className={
              backendOnline
                ? "status-dot online"
                : "status-dot offline"
            }
          />

          {backendOnline
            ? "System Online"
            : "Backend Offline"}

        </div>
        <div className="account-menu"><span>{user.name}</span><button onClick={handleLogout}>Sign out</button></div>
        </div>

      </header>


      {/* -------------------------------- */}
      {/* MAIN DASHBOARD */}
      {/* -------------------------------- */}

      <main className="dashboard">


        {/* -------------------------------- */}
        {/* MAP */}
        {/* -------------------------------- */}

        <section className="map-section">

          {/* <MapView
            network={network}
            routes={routes}
            vehicles={vehicles}
          /> */}

        <div className="route-selector">
  <span className="route-label">Choose Route</span>

  <button
    className={`route-button ${selectedRoute === "normal" ? "active primary" : ""}`}
    onClick={() => setSelectedRoute("normal")}
  >
    <span className="route-dot primary-dot"></span>
    Primary Route
  </button>

  <button
    className={`route-button ${selectedRoute === "safer" ? "active safer" : ""}`}
    onClick={() => setSelectedRoute("safer")}
  >
    <span className="route-dot safer-dot"></span>
    AI Safer Route
  </button>
</div>

          {/* <MapView
          network={network}
          routes={routes}
          vehicles={vehicles}
          incidents={incidents}
          /> */}
      <MapView
        network={network}
        routes={routes}
        vehicles={vehicles}
        incidents={incidents}
        selectedRoute={selectedRoute}
        onSelectRoute={setSelectedRoute}
        selectedIncidentType={selectedIncidentType}
      />

        </section>


        {/* -------------------------------- */}
        {/* SIDEBAR */}
        {/* -------------------------------- */}

        <aside className="sidebar">


          {/* ALERT PANEL */}

          <AlertPanel
            risk={risk}
            weather={weather}
            routes={routes}
          />

          {/* {NotificationPanel} */}

          <NotificationPanel
          risk={risk}
          weather={weather}
          routes={routes}
          incidents={incidents}
          />


          {/* INCIDENT FORM */}

          <IncidentForm
            onIncidentAdded={
              handleIncidentAdded
            }
            onTypeChange={setSelectedIncidentType}
          />


          {/* -------------------------------- */}
          {/* ACTIVE INCIDENTS */}
          {/* -------------------------------- */}

          <div className="panel">

            <div className="panel-title">
              Active Incidents
            </div>


            {incidents.length === 0 ? (

              <p className="empty">
                No active incidents.
              </p>

            ) : (

              incidents.map(
                (incident) => (

                  <div
                    className="incident"
                    key={incident.id}
                  >

                    <strong>
                      {incident.type}
                    </strong>

                    <span>
                      {incident.severity}
                    </span>

                    <p>
                      {incident.description}
                    </p>

                  </div>

                )
              )

            )}

          </div>


        </aside>


      </main>


    </div>

  );

}


export default App;
