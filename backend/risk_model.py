"""
Risk Prediction Layer for SETU-NER.

Provides two clearly separated functions:
- Landslide initiation susceptibility from the trained Sikkim Random Forest.
- A heuristic disruption indicator from available weather and nearby reported incidents.

The heuristic indicator is not a calibrated probability and must not be presented as one.
"""

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
SUSCEPTIBILITY_MODEL_PATH = BASE_DIR / "model" / "models" / "random_forest_final_v3.joblib"
SUSCEPTIBILITY_SCHEMA_PATH = BASE_DIR / "model" / "models" / "feature_schema_v3.json"
_SUSCEPTIBILITY_MODEL = None
_SUSCEPTIBILITY_FEATURES: Optional[List[str]] = None

def predict_landslide_susceptibility(features: Dict[str, float], segment_id: Optional[str] = None) -> Dict[str, Any]:
    """Run the trained Sikkim terrain model. This is not disruption probability."""
    global _SUSCEPTIBILITY_MODEL, _SUSCEPTIBILITY_FEATURES
    if not SUSCEPTIBILITY_MODEL_PATH.exists() or not SUSCEPTIBILITY_SCHEMA_PATH.exists():
        raise RuntimeError("Sikkim susceptibility model or feature schema is missing from model/models.")
    try:
        if _SUSCEPTIBILITY_MODEL is None:
            import joblib
            with open(SUSCEPTIBILITY_SCHEMA_PATH, "r", encoding="utf-8") as stream:
                schema = json.load(stream)
            metadata_path = SUSCEPTIBILITY_MODEL_PATH.parent / "model_metadata_v3.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
            _SUSCEPTIBILITY_FEATURES = metadata.get("features") or list(schema.get("numerical_features", {})) + list(schema.get("categorical_features", {}))
            _SUSCEPTIBILITY_MODEL = joblib.load(SUSCEPTIBILITY_MODEL_PATH)
    except Exception as exc:
        logger.exception("Could not load the Sikkim susceptibility model")
        raise RuntimeError(f"Could not load the trained model: {exc}") from exc

    expected = set(_SUSCEPTIBILITY_FEATURES or [])
    supplied = set(features)
    missing = sorted(expected - supplied)
    extra = sorted(supplied - expected)
    if missing or extra:
        detail = []
        if missing:
            detail.append("missing features: " + ", ".join(missing))
        if extra:
            detail.append("unexpected features: " + ", ".join(extra))
        raise ValueError("; ".join(detail))
    invalid = sorted(name for name in expected if not math.isfinite(float(features[name])))
    if invalid:
        raise ValueError("features must be finite numbers: " + ", ".join(invalid))
    try:
        import pandas as pd
        row = pd.DataFrame([[float(features[name]) for name in _SUSCEPTIBILITY_FEATURES]], columns=_SUSCEPTIBILITY_FEATURES)
        model = _SUSCEPTIBILITY_MODEL
        probability = float(model.predict_proba(row)[0][1])
    except Exception as exc:
        logger.exception("Sikkim susceptibility inference failed")
        raise RuntimeError(f"Model inference failed: {exc}") from exc

    level = "HIGH" if probability >= 0.65 else "MEDIUM" if probability >= 0.35 else "LOW"
    return {
        "model": "random_forest_final_v3",
        "segment_id": segment_id,
        "model_acceptance_criteria_passed": False,
        "geography": "Sikkim",
        "output_type": "LANDSLIDE_INITIATION_SUSCEPTIBILITY",
        "susceptibility_probability": round(probability, 6),
        "susceptibility_level": level,
        "risk_factors": [],
        "explanation": "No local per-prediction feature attribution is available from this model artifact.",
        "disruption_probability": None,
        "disclaimer": "Baseline terrain susceptibility only; not road closure, disruption, or real-time hazard probability.",
    }


def calculate_segment_risk(
    segment_id: str,
    base_risk: float = 0.0,
    rainfall_mm: float = 0.0,
    visibility_km: float = 10.0,
    slope_deg: float = 0.0,
    traffic_density: float = 0.0,
    active_incidents: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Calculate risk probability and identify key risk factors for a specific segment.

    Returns:
        {
            "segment_id": str,
            "risk_probability": float in [0.0, 1.0],
            "risk_level": "LOW" | "MEDIUM" | "HIGH",
            "risk_factors": list of str,
            "score": float in [0.0, 100.0]
        }
    """
    risk_factors: List[str] = []

    # Normalize the supplied static baseline (0 to 100 -> 0 to 1).
    p_base = min(max(base_risk / 100.0 if base_risk > 1.0 else base_risk, 0.0), 1.0)

    # 2. Factor in Environmental Metrics
    # Rainfall component (0-100 mm scale)
    p_rain = min(rainfall_mm / 100.0, 1.0)
    if rainfall_mm >= 45.0:
        risk_factors.append(f"Heavy Monsoon Precipitation ({rainfall_mm:.1f} mm)")
    elif rainfall_mm >= 25.0:
        risk_factors.append(f"Moderate Rainfall ({rainfall_mm:.1f} mm)")

    # Visibility component (fog / mist)
    p_vis = max(0.0, min((5.0 - visibility_km) / 5.0, 1.0))
    if visibility_km <= 2.5:
        risk_factors.append(f"Dense Fog / Restricted Visibility ({visibility_km:.1f} km)")

    # Slope component (mountain terrain slope > 30 degrees is high risk for landslides)
    p_slope = min(slope_deg / 45.0, 1.0)
    if slope_deg >= 30.0:
        risk_factors.append(f"Steep Mountain Incline ({slope_deg:.1f}° slope)")
    elif slope_deg >= 20.0:
        risk_factors.append(f"Moderate Mountain Gradient ({slope_deg:.1f}° slope)")

    # Traffic congestion component
    p_traffic = min(max(traffic_density, 0.0), 1.0)
    if traffic_density >= 0.75:
        risk_factors.append("High Convoy Traffic Density")

    # Combine weighted environmental components
    p_env = (
        0.35 * p_rain +
        0.25 * p_vis +
        0.25 * p_slope +
        0.15 * p_traffic
    )

    # Blend terrain baseline with dynamic environmental state
    blended_prob = 0.50 * p_base + 0.50 * p_env

    # 3. Dynamic Incident Boosting
    incident_boost = 0.0
    if active_incidents:
        for inc in active_incidents:
            sev = str(inc.get("severity", "")).upper()
            inc_type = str(inc.get("type", "INCIDENT")).replace("_", " ").title()
            if sev == "HIGH":
                incident_boost += 0.25
                risk_factors.append(f"Critical Field Report: {inc_type}")
            elif sev == "MEDIUM":
                incident_boost += 0.12
                risk_factors.append(f"Moderate Field Alert: {inc_type}")

    final_probability = min(1.0, max(0.0, round(blended_prob + incident_boost, 4)))
    final_score = round(final_probability * 100.0, 2)

    # 4. Classify Risk Level
    if final_probability >= 0.65:
        risk_level = "HIGH"
    elif final_probability >= 0.35:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    if not risk_factors:
        risk_factors.append("Nominal Mountain Corridor Baseline")

    return {
        "segment_id": str(segment_id),
        "risk_probability": final_probability,
        "risk_level": risk_level,
        "risk_factors": list(dict.fromkeys(risk_factors)),  # unique preserve order
        "score": final_score,
    }


def predict_risk(features: dict) -> Dict[str, Any]:
    """
    Backwards-compatible API route helper.
    Accepts {rainfall, visibility, traffic, slope} and returns {score, level}.
    """
    rainfall = float(features.get("rainfall", 0.0))
    visibility = float(features.get("visibility", 10.0))
    traffic = float(features.get("traffic", 0.0))
    slope_value = float(features.get("slope", 0.0))
    slope = slope_value * 45.0 if 0.0 <= slope_value <= 1.0 else slope_value

    result = calculate_segment_risk(
        segment_id="route_overview",
        base_risk=30.0,
        rainfall_mm=rainfall,
        visibility_km=visibility,
        slope_deg=slope,
        traffic_density=traffic,
    )

    return {
        "score": result["score"],
        "level": result["risk_level"],
        "probability": None,
        "risk_indicator": result["score"],
        "risk_factors": result["risk_factors"],
    }
