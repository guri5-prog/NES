# Synthetic Data Validation Report

Generated: 2026-10-30T15:32:31.489357+00:00

- Candidate 4 rows: 838
- Synthetic susceptibility rows: 4000
- Synthetic road scenarios: 6000
- Frontend preview records: 2838
- All checks passed: **True**

## Checks

| Check | Passed |
|---|---|
| susceptibility_record_count | True |
| road_record_count | True |
| all_synthetic_provenance | True |
| no_synthetic_susceptibility_target | True |
| road_labels_marked_simulated | True |
| simulation_scores_in_range | True |

## Limitations
- Synthetic susceptibility rows have no independent ground-truth labels.
- Teacher predictions reproduce the existing RF and are not new observations.
- Road disruption labels are simulation-rule outputs, not verified closures.
- Even when a real OSM ID is attached, Candidate 4 environmental anchors have not been spatially extracted for that specific road segment.
- Scores are not calibrated probabilities. SIM_ONLY IDs must not be used for real routing.