function AlertPanel({
  risk,
  weather,
  routes,
}) {

  if (!risk || !routes) {

    return (
      <div className="panel">
        Loading AI analysis...
      </div>
    );

  }


  const prediction =
    risk.prediction;


  const primaryRisk =
    routes.normal?.risk_score ?? 0;


  const saferRisk =
    routes.safer?.risk_score ?? 0;


  const routeIsRisky =
    primaryRisk >= 70;


  let routeStatus = "LOW";

  if (primaryRisk >= 70) {
    routeStatus = "HIGH";
  } else if (primaryRisk >= 40) {
    routeStatus = "MEDIUM";
  }


  return (

    <div className="panel">

      <div className="panel-title">
        AI Risk Assessment
      </div>


      {/* AI ENVIRONMENT RISK */}

      <div
        className={
          `risk-card ${
            prediction.level.toLowerCase()
          }`
        }
      >

        <div className="risk-label">
          Environmental Risk
        </div>

        <div className="risk-score">
          {prediction.score}
        </div>

        <div className="risk-level">
          {prediction.level}
        </div>

      </div>


      {/* PRIMARY ROUTE */}

      <div className="weather-section">

        <h3>
          Primary Route Risk
        </h3>

        <p>
          Score:{" "}
          <strong>
            {primaryRisk}
          </strong>
        </p>

        <p>
          Status:{" "}
          <strong>
            {routeStatus}
          </strong>
        </p>

      </div>


      {/* WEATHER */}

      {weather && (

        <div className="weather-section">

          <h3>
            Current Conditions
          </h3>

          <p>
            {weather.condition}
          </p>

          <p>
            Rainfall:{" "}
            {weather.rainfall_mm} mm
          </p>

          <p>
            Visibility:{" "}
            {weather.visibility_km} km
          </p>

        </div>

      )}


      {/* AI ROUTE RECOMMENDATION */}

      {routeIsRisky && (

        <div className="recommendation">

          <h3>
            Safer Route Recommended
          </h3>

          <p>

            The primary route has a
            high predicted risk.

            The routing engine identified
            an alternate path with
            significantly lower risk.

          </p>


          <div className="route-stats">

            <span>
              Risk: {saferRisk}
            </span>

            <span>
              {routes.safer.distance_km} km
            </span>

          </div>

        </div>

      )}

    </div>

  );
}


export default AlertPanel;