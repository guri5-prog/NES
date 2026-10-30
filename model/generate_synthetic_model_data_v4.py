#!/usr/bin/env python
"""Generate corrected, provenance-aware Sikkim synthetic scenarios.

This version fixes categorical jitter, derived-feature inconsistencies, and
OSM edge identifiers. It DOES NOT perform raster/GIS feature extraction.
Road environmental features are intentionally not copied from unrelated
Candidate 4 points onto road segments.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_ROOT = Path(r"C:\ProgramData\aTubeCatcher\peoject\NES\NES\ml")
SEED = 42

# Candidate 4 environmental predictors. Metadata, coordinates, labels and IDs
# are intentionally excluded from the susceptibility model feature matrix.
CONTINUOUS_BASE = [
    "elevation", "slope", "curvature_total", "plan_curvature",
    "profile_curvature", "terrain_ruggedness_tri",
    "topographic_position_tpi", "clay_0_5cm", "clay_5_15cm",
    "sand_0_5cm", "sand_5_15cm", "soc_0_5cm", "soc_5_15cm",
    "phh2o_0_5cm", "phh2o_5_15cm", "distance_to_roads_m",
]
DERIVED_DIFFS = {
    "clay_diff_5_15_minus_0_5": ("clay_5_15cm", "clay_0_5cm"),
    "sand_diff_5_15_minus_0_5": ("sand_5_15cm", "sand_0_5cm"),
    "soc_diff_5_15_minus_0_5": ("soc_5_15cm", "soc_0_5cm"),
    "ph_diff_5_15_minus_0_5": ("phh2o_5_15cm", "phh2o_0_5cm"),
}
CATEGORICAL = ["landcover_code"]
BOOL_COLS = ["is_flat_aspect"]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def find_file(root: Path, name: str):
    direct = root / name
    if direct.exists():
        return direct
    matches = list(root.rglob(name))
    return matches[0] if matches else None


def find_candidate(root: Path):
    p = find_file(root, "candidate_4_full_corrected_model_ready.csv")
    if p is None:
        raise FileNotFoundError("Candidate 4 CSV was not found under --ml-root.")
    return p


def find_model(root: Path):
    return find_file(root, "final_random_forest_pipeline.joblib")


def find_roads(root: Path, explicit: Path | None):
    if explicit:
        if not explicit.exists():
            raise FileNotFoundError(f"Road file not found: {explicit}")
        return explicit
    p = find_file(root, "sikkim_roads.geojson")
    if p:
        return p
    for pattern in ("*roads*.gpkg", "*roads*.geojson", "*roads*.shp"):
        matches = list(root.rglob(pattern))
        if matches:
            return matches[0]
    return None


def read_roads_geojson(path: Path):
    """Read OSMnx edge GeoJSON and build one stable ID per edge (u,v,key)."""
    import geopandas as gpd

    gdf = gpd.read_file(path)
    required = {"u", "v", "key"}
    if not required.issubset(gdf.columns):
        raise ValueError(
            "Expected OSMnx edge properties u, v and key. "
            f"Found columns: {gdf.columns.tolist()}"
        )

    out = pd.DataFrame(index=gdf.index)
    out["segment_id"] = (
        gdf["u"].astype(str) + "_" + gdf["v"].astype(str) + "_" + gdf["key"].astype(str)
    )
    out["u"] = gdf["u"].astype(str)
    out["v"] = gdf["v"].astype(str)
    out["edge_key"] = gdf["key"].astype(str)
    out["osm_way_ids"] = gdf["osmid"].apply(
        lambda x: json.dumps(x if isinstance(x, (list, tuple)) else [x])
    ) if "osmid" in gdf else "[]"
    out["road_name"] = gdf["name"].fillna("").astype(str) if "name" in gdf else ""
    out["road_type"] = gdf["highway"].apply(
        lambda x: json.dumps(x) if isinstance(x, (list, tuple)) else str(x)
    ) if "highway" in gdf else "unknown"
    out["segment_length_m"] = pd.to_numeric(
        gdf["length"], errors="coerce"
    ) if "length" in gdf else np.nan

    # Geometry centroid is emitted in lon/lat for reference only.
    geom = gdf.geometry
    out["centroid_longitude"] = geom.centroid.x
    out["centroid_latitude"] = geom.centroid.y
    out["geometry_type"] = geom.geom_type.astype(str)
    out = out.reset_index(drop=True)
    if out["segment_id"].duplicated().any():
        raise ValueError("Composite OSM edge identifiers are not unique.")
    return out


def generate_susceptibility(real: pd.DataFrame, n: int, seed: int):
    rng = np.random.default_rng(seed)
    available_cont = [c for c in CONTINUOUS_BASE if c in real.columns]
    if not available_cont:
        raise ValueError("No expected continuous environmental predictors found in Candidate 4.")

    idx = rng.integers(0, len(real), n)
    out = real.iloc[idx].copy().reset_index(drop=True)
    parent_ids = real.iloc[idx].index.astype(str).tolist()

    # Jitter only continuous source measurements; never jitter codes, booleans,
    # coordinates, IDs, metadata, or already-derived difference columns.
    for col in available_cont:
        vals = pd.to_numeric(real[col], errors="coerce").dropna().astype(float)
        if vals.empty:
            continue
        lo, hi = vals.quantile([0.01, 0.99])
        sd = float(vals.std()) if len(vals) > 1 else 0.0
        x = pd.to_numeric(out[col], errors="coerce").to_numpy(dtype=float)
        out[col] = np.clip(x + rng.normal(0.0, max(sd * 0.02, 1e-12), n), lo, hi)

    # Recompute derived soil differences after perturbing source measurements.
    for diff_col, (upper, lower) in DERIVED_DIFFS.items():
        if diff_col in out.columns and upper in out.columns and lower in out.columns:
            out[diff_col] = (
                pd.to_numeric(out[upper], errors="coerce")
                - pd.to_numeric(out[lower], errors="coerce")
            )

    # Keep aspect representation internally consistent.
    if "aspect" in out.columns:
        aspect = pd.to_numeric(out["aspect"], errors="coerce").to_numpy(dtype=float)
        radians = np.deg2rad(np.mod(aspect, 360.0))
        if "aspect_sin" in out.columns:
            out["aspect_sin"] = np.sin(radians)
        if "aspect_cos" in out.columns:
            out["aspect_cos"] = np.cos(radians)

    # Remove any labels/fold identifiers. No synthetic target is created.
    remove = [
        c for c in out.columns
        if any(token in str(c).lower() for token in ("target", "label", "fold"))
    ]
    out = out.drop(columns=remove, errors="ignore")
    out.insert(0, "record_id", [f"SYN_SUS_{i+1:06d}" for i in range(n)])
    out["data_origin"] = "synthetic"
    out["parent_record_id"] = parent_ids
    out["generation_method"] = "anchor_sampling_continuous_2pct_jitter_v2"
    out["generator_version"] = "2.0"
    out["label_source"] = "none"
    out["label_is_observed"] = False
    out["random_seed"] = seed
    return out, available_cont


def add_teacher_predictions(syn: pd.DataFrame, model_path: Path | None):
    syn["teacher_prediction"] = np.nan
    syn["teacher_prediction_status"] = "MODEL_NOT_FOUND"
    if model_path is None:
        return "Saved Random Forest not found; teacher predictions skipped."
    try:
        import joblib
        model = joblib.load(model_path)
        # Use only the model's declared input columns when available.
        expected = getattr(model, "feature_names_in_", None)
        if expected is not None:
            X = syn.reindex(columns=list(expected))
        else:
            X = syn.copy()
        if hasattr(model, "predict_proba"):
            probs = model.predict_proba(X)
            score = probs[:, 1] if probs.ndim == 2 and probs.shape[1] > 1 else probs.ravel()
        else:
            score = model.predict(X)
        syn["teacher_prediction"] = np.asarray(score, dtype=float)
        syn["teacher_prediction_status"] = "MODEL_GENERATED_NOT_GROUND_TRUTH"
        syn["teacher_model_version"] = "random_forest_existing_v1"
        return f"Teacher predictions generated by {model_path}"
    except Exception as exc:
        syn["teacher_prediction_status"] = f"PREDICTION_FAILED: {exc}"
        return f"Teacher prediction failed: {exc}"


def generate_road_scenarios(roads: pd.DataFrame, n: int, seed: int):
    """Generate scenario rows without falsely attaching unrelated point features."""
    rng = np.random.default_rng(seed + 100)
    chosen_idx = rng.integers(0, len(roads), n)
    out = roads.iloc[chosen_idx].reset_index(drop=True).copy()
    out.insert(0, "scenario_id", [f"SYN_ROAD_{i+1:06d}" for i in range(n)])

    # Scenario rainfall is synthetic, not an observed forecast or historical value.
    rainfall_1d = rng.gamma(shape=2.0, scale=18.0, size=n)
    rainfall_3d = rainfall_1d * rng.uniform(1.2, 2.8, n)
    rainfall_7d = rainfall_3d * rng.uniform(1.1, 2.5, n)
    categories = np.array([
        "NORMAL_CONDITIONS", "HEAVY_RAINFALL", "PROLONGED_RAINFALL",
        "STEEP_TERRAIN_EXPOSURE", "RIVER_FLOOD_EXPOSURE"
    ])
    strata = np.arange(n) % len(categories)
    rng.shuffle(strata)
    out["rainfall_1d_synthetic_mm"] = rainfall_1d
    out["rainfall_3d_synthetic_mm"] = rainfall_3d
    out["rainfall_7d_synthetic_mm"] = rainfall_7d
    out["scenario_category"] = categories[strata]

    # No risk score or disruption label is calculated here: without GIS-derived
    # segment features and observed closures, that would imply false precision.
    out["risk_probability"] = np.nan
    out["risk_score"] = np.nan
    out["disruption_label"] = "NOT_ESTIMATED"
    out["simulation_status"] = "SCENARIO_INPUT_ONLY_NOT_A_PREDICTION"
    out["data_origin"] = "synthetic"
    out["label_source"] = "none"
    out["label_is_observed"] = False
    out["generator_version"] = "2.0"
    out["random_seed"] = seed
    out["environmental_features_status"] = "NOT_EXTRACTED_FROM_SEGMENT_GEOMETRY"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ml-root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--roads", type=Path, default=None,
                    help="Optional explicit path to sikkim_roads.geojson")
    ap.add_argument("--susceptibility-count", type=int, default=4000)
    ap.add_argument("--road-count", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()
    if args.susceptibility_count < 1 or args.road_count < 1:
        raise ValueError("Record counts must be positive.")

    root = args.ml_root.resolve()
    here = Path(__file__).resolve().parent
    outputs, reports = here / "outputs_v2", here / "reports_v2"
    outputs.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)

    candidate = find_candidate(root)
    real = pd.read_csv(candidate)
    roads_path = find_roads(root, args.roads)
    if roads_path is None:
        raise FileNotFoundError("Road GeoJSON not found. Pass --roads explicitly.")
    roads = read_roads_geojson(roads_path)

    print(f"[INFO] Candidate 4: {len(real)} rows x {len(real.columns)} columns")
    print(f"[INFO] Road GeoJSON: {roads_path}")
    print(f"[INFO] Unique OSM edge segments: {len(roads)}")

    susceptibility, feature_cols = generate_susceptibility(
        real, args.susceptibility_count, args.seed
    )
    model_path = find_model(root)
    teacher_msg = add_teacher_predictions(susceptibility, model_path)
    road_scenarios = generate_road_scenarios(
        roads, args.road_count, args.seed
    )

    sus_path = outputs / "susceptibility_synthetic_v2.csv"
    teacher_path = outputs / "susceptibility_teacher_predictions_v2.csv"
    road_path = outputs / "road_scenarios_inputs_v2.csv"
    roads_path_out = outputs / "road_segment_catalog_v2.csv"
    susceptibility.to_csv(sus_path, index=False)
    susceptibility[[
        "record_id", "teacher_prediction", "teacher_prediction_status",
        "data_origin", "parent_record_id"
    ]].to_csv(teacher_path, index=False)
    road_scenarios.to_csv(road_path, index=False)
    roads.to_csv(roads_path_out, index=False)

    # Explicit validation of categorical, Boolean and derived columns.
    checks = []
    if "landcover_code" in real and "landcover_code" in susceptibility:
        source_codes = set(pd.to_numeric(real.landcover_code, errors="coerce").dropna().unique())
        generated_codes = set(pd.to_numeric(susceptibility.landcover_code, errors="coerce").dropna().unique())
        checks.append(("landcover_codes_preserved", generated_codes.issubset(source_codes)))
    for col in BOOL_COLS:
        if col in real and col in susceptibility:
            checks.append((f"{col}_values_preserved",
                           set(susceptibility[col].dropna().unique()).issubset(set(real[col].dropna().unique()))))
    for diff_col, (upper, lower) in DERIVED_DIFFS.items():
        if all(c in susceptibility for c in (diff_col, upper, lower)):
            expected = susceptibility[upper] - susceptibility[lower]
            max_error = (expected - susceptibility[diff_col]).abs().max()
            checks.append((f"{diff_col}_recalculated", bool(max_error < 1e-8)))
    checks.extend([
        ("susceptibility_count", len(susceptibility) == args.susceptibility_count),
        ("road_scenario_count", len(road_scenarios) == args.road_count),
        ("unique_edge_ids", roads.segment_id.is_unique),
        ("one_segment_id_per_scenario", road_scenarios.segment_id.notna().all()),
        ("road_risk_not_fabricated", road_scenarios.risk_probability.isna().all()
         and road_scenarios.risk_score.isna().all()),
        ("synthetic_provenance", susceptibility.data_origin.eq("synthetic").all()
         and road_scenarios.data_origin.eq("synthetic").all()),
    ])
    report = {
        "generated_at": utc_now(),
        "generator_version": "2.0",
        "candidate4_path": str(candidate),
        "road_geojson_path": str(roads_path),
        "candidate4_rows": len(real),
        "road_edge_count": len(roads),
        "synthetic_susceptibility_rows": len(susceptibility),
        "synthetic_road_scenario_rows": len(road_scenarios),
        "checks": [{"check": name, "passed": bool(ok)} for name, ok in checks],
        "all_checks_passed": all(ok for _, ok in checks),
        "teacher_prediction_note": teacher_msg,
        "limitations": [
            "Synthetic susceptibility rows are not independent observations and have no ground-truth labels.",
            "Teacher predictions reproduce the existing Random Forest and are not ground truth.",
            "OSM edge IDs are composite u_v_key identifiers; osm_way_ids are retained separately.",
            "Road scenarios contain synthetic rainfall inputs only; environmental raster features have not been extracted.",
            "No road disruption probability, severity score, or closure label is produced.",
            "Do not use these scenario rows for operational routing or claim calibrated risk.",
        ],
    }
    write_json(reports / "validation_report_v2.json", report)
    write_json(outputs / "synthetic_data_manifest_v2.json", {
        "generated_at": report["generated_at"],
        "seed": args.seed,
        "generator_version": "2.0",
        "source_candidate4": str(candidate),
        "source_model": str(model_path) if model_path else None,
        "source_roads": str(roads_path),
        "files": {
            "susceptibility": str(sus_path),
            "teacher_predictions": str(teacher_path),
            "road_scenarios": str(road_path),
            "road_segment_catalog": str(roads_path_out),
            "validation": str(reports / "validation_report_v2.json"),
        },
        "semantics": {
            "susceptibility": "Unlabelled synthetic feature scenarios",
            "road_scenarios": "Synthetic scenario inputs only; not risk predictions",
            "risk_probability": "null",
        },
    })

    print("\nGENERATION COMPLETE")
    print(f"Susceptibility scenarios: {len(susceptibility)}")
    print(f"Road scenario inputs: {len(road_scenarios)}")
    print(f"Unique road edge segments: {len(roads)}")
    print(f"Teacher model: {teacher_msg}")
    print(f"Outputs: {outputs}")
    print(f"Validation report: {reports / 'validation_report_v2.json'}")
    print("Checks:")
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}: {name}")
    if not report["all_checks_passed"]:
        sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
