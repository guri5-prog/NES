import { useState } from "react";

const API_URL = "";

function IncidentForm({ onIncidentAdded, onTypeChange }) {

  const [type, setType] = useState("LANDSLIDE");
  const [severity, setSeverity] = useState("HIGH");
  const [description, setDescription] = useState("");

  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");


  async function handleSubmit(event) {

    event.preventDefault();

    setLoading(true);
    setMessage("");


    try {

      const response = await fetch(
        `${API_URL}/api/incidents`,
        {
          method: "POST",

          headers: {
            "Content-Type": "application/json",
          },

          body: JSON.stringify({
            type,
            severity,
            description:
              description ||
              `${type} reported on the primary corridor.`,
            lat: 25.365,
            lon: 91.735,
          }),
        }
      );


      if (!response.ok) {
        throw new Error(
          "Failed to report incident"
        );
      }


      const data =
        await response.json();


      // Send the new incident back to App.jsx
      if (onIncidentAdded) {
        onIncidentAdded(data.incident);
      }


      setMessage(
        "Incident reported successfully."
      );

      setDescription("");


    } catch (error) {

      console.error(error);

      setMessage(
        "Could not report incident."
      );

    } finally {

      setLoading(false);

    }

  }


  return (

    <div className="panel">

      <div className="panel-title">
        Report Incident
      </div>


      <form
        className="incident-form"
        onSubmit={handleSubmit}
      >

        {/* INCIDENT TYPE */}

        <label>

          Incident Type

          {/* <select
            value={type}
            onChange={(event) =>
              setType(event.target.value)
            }
          >

            <option value="LANDSLIDE">
              Landslide
            </option>

            <option value="FLOOD">
              Flood
            </option>

            <option value="ACCIDENT">
              Accident
            </option>

            <option value="LOW_VISIBILITY">
              Low Visibility
            </option>

            <option value="ROAD_BLOCK">
              Road Block
            </option>

          </select> */}
          <select
          value={type}
          onChange={(event) => {
            const newType = event.target.value;
            setType(newType);
            if (onTypeChange) {
              onTypeChange(newType);
            }
          }}>
          <option value="LANDSLIDE">Landslide</option>
          <option value="FLOOD">Flood</option>
          <option value="ACCIDENT">Accident</option>
          <option value="LOW_VISIBILITY">Low Visibility</option>
          <option value="ROAD_BLOCK">Road Block</option>
          
          </select>

        </label>


        {/* SEVERITY */}

        <label>

          Severity

          <select
            value={severity}
            onChange={(event) =>
              setSeverity(event.target.value)
            }
          >

            <option value="HIGH">
              High
            </option>

            <option value="MEDIUM">
              Medium
            </option>

            <option value="LOW">
              Low
            </option>

          </select>

        </label>


        {/* DESCRIPTION */}

        <label>

          Description

          <textarea
            value={description}
            onChange={(event) =>
              setDescription(
                event.target.value
              )
            }
            placeholder="Describe the incident..."
          />

        </label>


        {/* SUBMIT */}

        <button
          type="submit"
          disabled={loading}
        >

          {loading
            ? "Reporting..."
            : "Report Incident"}

        </button>


        {/* STATUS */}

        {message && (

          <p>
            {message}
          </p>

        )}

      </form>

    </div>

  );

}


export default IncidentForm;
