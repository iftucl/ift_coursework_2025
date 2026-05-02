# Formal Slim Data Package

Baseline run id: `6905e84b-9e16-4106-8c0f-cd9ecce56728`  
Baseline portfolio: `cw2_formal_20260420_fund_ra3_s30_t50`  
Cutoff date: `2026-04-20`  
Generated at: `2026-04-29T18:10:17.451820+00:00`

This package is the cleaned handoff scope for robustness testing. It keeps full
PIT input data needed to rerun portfolio scenarios, plus the official baseline
run outputs for comparison. Historical sweep outputs, old reports, and
operational log tables are excluded.

## Main Contents

- `db_csv/systematic_equity/`: filtered CSV.GZ database tables.
- `key_artifacts/formal_config/`: official formal configuration.
- `key_artifacts/formal_report/`: official report, charts, and trade blotter artifact.
- `key_artifacts/formal_sweep/`: formal ranking that selected the baseline candidate.
- `DATA_VERSION_PROOF.md`: row counts, cutoff proof, and PIT notes.
- `FORMAL_SLIM_DATA_SCOPE.md`: exact inclusion/exclusion scope.

Use this package together with the current code repository if the next owner
needs to rerun robustness tests.
