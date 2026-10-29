"""
Risk prediction layer.

The production architecture can use a trained ML model.
For the MVP, a deterministic fallback is provided so the demo
continues working even without a trained model.
"""

from pathlib import Path
import joblib


MODEL_PATH = Path(__file__).parent / "data" / "risk_model.joblib"


def load_model():
    if MODEL_PATH.exists():
        try:
            return joblib.load(MODEL_PATH)
        except Exception:
            return None

    return None


model = load_model()


def calculate_fallback_risk(
    rainfall: float,
    visibility: float,
    traffic: float,
    slope: float,
):
    """
    Demo-safe risk calculation.

    Produces a score from 0–100.
    """

    rainfall_score = min(rainfall / 80 * 100, 100)

    visibility_score = max(
        0,
        min((5 - visibility) / 5 * 100, 100)
    )

    traffic_score = traffic * 100

    slope_score = slope * 100

    score = (
        rainfall_score * 0.35
        + visibility_score * 0.25
        + traffic_score * 0.15
        + slope_score * 0.25
    )

    return round(max(0, min(score, 100)), 2)


def predict_risk(features: dict):
    """
    Predict road risk.

    Uses trained model if available.
    Otherwise uses the deterministic fallback.
    """

    rainfall = features["rainfall"]
    visibility = features["visibility"]
    traffic = features["traffic"]
    slope = features["slope"]

    if model is not None:
        try:
            prediction = model.predict([[
                rainfall,
                visibility,
                traffic,
                slope,
            ]])

            score = float(prediction[0])

            # Normalize if model outputs 0–1
            if score <= 1:
                score *= 100

            score = max(0, min(score, 100))

        except Exception:
            score = calculate_fallback_risk(
                rainfall,
                visibility,
                traffic,
                slope,
            )
    else:
        score = calculate_fallback_risk(
            rainfall,
            visibility,
            traffic,
            slope,
        )

    if score >= 70:
        level = "HIGH"
    elif score >= 40:
        level = "MEDIUM"
    else:
        level = "LOW"

    return {
        "score": round(score, 2),
        "level": level,
    }