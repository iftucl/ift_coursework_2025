# Start Here

This note is the GitHub-facing entry point for the current formal CW2 strategy.
It points to the tracked code, configuration, report, design evidence, and
exact-reproduction contract.

## What to open first

1. `REFERENCE_STRATEGY_SUMMARY.md`
   This states the current formal CW2 strategy, including which optional modules were implemented in code but not switched on.

2. `DATA_DELIVERY_SUMMARY.md`
   This explains how the code package, frozen data exports, table definitions, and report outputs fit together.

3. `team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report.md`
   This is the current formal report package, with the companion JSON summary,
   trade blotter, and generated figures in the same directory.

## Main contents

- Current repository checkout / GitHub branch
  The canonical source for code, schemas, configs, tests, and documentation.
  Older local code tarballs are historical unless regenerated from the current
  branch after these formal-reference updates.

- `team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report.md`
  The current formal benchmark report.

- `team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report_summary.json`
  The compact summary for the current formal run.

- `team_Pearson/coursework_two/docs/strategy_design_decision_log_20260420.md`
  The formal design and selection decision log. This is the main explanation of
  why the final strategy is `fund_ra3_s30_t50`, how mini sweep and micro-alpha
  search were used, and why the later active-band research candidate was not
  promoted to the formal strategy.

- `team_Pearson/coursework_two/docs/formal_strategy_briefing_20260420.md`
  A concise formal briefing for the current formal strategy, including
  the five alpha factor groups and the separate factor covariance risk model.

- `team_Pearson/coursework_two/repro/reference_run_20260420.json`
  The machine-readable formal reference contract for run
  `6905e84b-9e16-4106-8c0f-cd9ecce56728`.

- `team_Pearson/coursework_two/repro/reference_summary_20260420.md`
  A short human-readable summary for the current formal run.

## Build and check command

Run the CW2 code-quality and coverage gate from the repository root:

```bash
team_Pearson/coursework_two/scripts/run_quality_checks.sh
```

Use `--docs` when the shared CW1+CW2 Sphinx site should be rebuilt as part of
the same validation pass.

## Important boundary

This bundle is designed to make the current formal strategy and its reported
outputs clear without asking the recipient to inspect the codebase manually.
The Git-tracked reproduction path is the formal config, report, sweep evidence,
and `team_Pearson/coursework_two/repro/` contract. Exact database-state replay
requires the separately generated formal release assets described in
`team_Pearson/coursework_two/repro/README.md`.
