import pandas as pd
from pathlib import Path

p = Path("outputs")

sus = pd.read_csv(p / "susceptibility_synthetic.csv")
road = pd.read_csv(p / "road_disruption_synthetic.csv")

print("\n--- SUSCEPTIBILITY AUDIT ---")
print("Duplicate record IDs:", sus["record_id"].duplicated().sum())
print("Landcover values:", sorted(sus["landcover_code"].dropna().unique())[:30])
print("Landcover unique count:", sus["landcover_code"].nunique())

for base, top, diff in [
    ("clay_0_5cm", "clay_5_15cm", "clay_diff_5_15_minus_0_5"),
    ("sand_0_5cm", "sand_5_15cm", "sand_diff_5_15_minus_0_5"),
    ("soc_0_5cm", "soc_5_15cm", "soc_diff_5_15_minus_0_5"),
    ("phh2o_0_5cm", "phh2o_5_15cm", "ph_diff_5_15_minus_0_5"),
]:
    actual = sus[top] - sus[base]
    error = (actual - sus[diff]).abs()
    print(f"{diff}: maximum inconsistency = {error.max():.6f}")

print("\n--- ROAD AUDIT ---")
print("Duplicate road records:", road.duplicated().sum())
print("Unique segment IDs:", road["segment_id"].nunique())
print("Missing segment IDs:", road["segment_id"].isna().sum())
print("Segment ID examples:")
print(road["segment_id"].head(10).to_string(index=False))
print("Segment ID status:")
print(road["segment_id_status"].value_counts(dropna=False))
print("Missing coordinates:", road[["x_utm", "y_utm"]].isna().sum().to_dict())
