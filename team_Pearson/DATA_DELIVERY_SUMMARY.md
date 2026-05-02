# Data Delivery Summary

This note explains what should be handed over if the recipient needs not only
the code, but also the definitions and outputs for the current CW2 formal
strategy.

## 1. What the code archive covers

The code archive is suitable for:

- strategy logic
- configuration
- factor and portfolio construction rules
- table schemas
- scripts and orchestration
- the reference strategy summary

It is not sufficient on its own for:

- exact factor-level result inspection
- exact portfolio-target inspection
- exact backtest-result inspection
- exact numerical reproduction of the reported performance

For those, a frozen data and results package is also needed.

## 2. Recommended handover structure

For a clean handover, the delivery should be split into two parts.

### A. Code and strategy package

Send:

- the current GitHub branch / repository checkout

This already includes:

- source code
- configuration files
- SQL schemas
- tests
- documentation source
- `REFERENCE_STRATEGY_SUMMARY.md`

This package tells the recipient:

- what the current formal strategy is
- which optional modules existed in code
- which optional modules were not active in the formal strategy

### B. Report, evidence, and optional data package

For the current formal interpretation from a GitHub checkout, use these
Git-tracked formal artefacts:

- `team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report.md`
- `team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report_summary.json`
- `team_Pearson/coursework_two/outputs/formal_sweeps/20260429T031646Z/`
- `team_Pearson/coursework_two/outputs/micro_alpha_sweeps/20260429T021834Z/`
- `team_Pearson/coursework_two/docs/strategy_design_decision_log_20260420.md`
- `team_Pearson/coursework_two/docs/formal_strategy_briefing_20260420.md`
- `team_Pearson/coursework_two/docs/research_upgrade_activeband_20260428.md`
- `team_Pearson/coursework_two/repro/reference_run_20260420.json`

The local `team_Pearson/coursework_two/outputs/handoff/` directory is an
optional release-artifact packaging area for frozen database exports generated
by `team_Pearson/coursework_two/scripts/export_repro_bundle.sh`. It is not
required for understanding the formal strategy from the repository, and it
should not be treated as the primary Git-tracked reproduction entrypoint.

If the recipient needs exact SQL-table inspection or frozen database replay,
send a separately labelled formal release artifact generated for run
`6905e84b-9e16-4106-8c0f-cd9ecce56728`.

Taken together, the Git-tracked formal report, sweep evidence, strategy design
log, and reference contract tell the recipient:

- which run is the current formal baseline
- what exact SQL-backed outputs were materialised
- what final report package and trade blotter were generated
- how the final ra3-s30-t50 design was selected
- why the development-only active-band candidate was not adopted
- and how to verify the formal run against the reference summary

## 3. Where the definitions live

If the recipient needs definitions for factor layers, portfolio outputs, and backtest metrics, the definitions are split across configuration, README notes, and SQL schemas.

### A. First-level factor and feature definitions

Use:

- `team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml`
- `team_Pearson/coursework_two/README.md`
- `team_Pearson/coursework_two/sql/cw2_feature_schema.sql`

These define:

- factor groups such as quality, value, market technical, sentiment, and dividend
- the sub-variables under each factor group
- preprocessing rules
- investable-universe rules
- risk-overlay rules
- the PostgreSQL tables used for feature outputs

The main feature-layer outputs are:

- `systematic_equity.feature_universe_screen`
- `systematic_equity.feature_sub_scores`
- `systematic_equity.feature_factor_scores`
- `systematic_equity.feature_risk_overlay`
- `systematic_equity.feature_snapshot_registry`

### B. Second-level portfolio and target definitions

Use:

- the same pinned CW2 configuration file
- `team_Pearson/coursework_two/README.md`
- `team_Pearson/coursework_two/sql/cw2_feature_schema.sql`

These define:

- target-generation frequency
- selection rules
- weighting method
- portfolio constraints
- covariance settings, including the formal `fundamental_factor` risk model
  used by the mean-variance optimizer
- target-position outputs

The main portfolio-layer outputs are:

- `systematic_equity.portfolio_target_positions`
- `systematic_equity.portfolio_construction_diagnostics`
- `systematic_equity.portfolio_snapshot_registry`
- `systematic_equity.model_input_manifests`

### C. Backtest and analysis definitions

Use:

- `team_Pearson/coursework_two/README.md`
- `team_Pearson/coursework_two/sql/cw2_backtest_schema.sql`
- `team_Pearson/coursework_two/sql/cw2_analysis_schema.sql`
- `team_Pearson/coursework_two/sql/cw2_reporting_schema.sql`

These define:

- run metadata
- holdings and NAV history
- metric tables
- relative metrics
- regime attribution
- covariance diagnostics
- scorecard outputs
- reporting outputs

The main backtest and analysis outputs are:

- `systematic_equity.backtest_runs`
- `systematic_equity.backtest_holdings`
- `systematic_equity.backtest_performance`
- `systematic_equity.backtest_metrics`
- `systematic_equity.backtest_relative_metrics`
- `systematic_equity.backtest_regime_attribution`
- `systematic_equity.backtest_covariance_metrics`
- `systematic_equity.backtest_covariance_contributions`
- `systematic_equity.backtest_scorecard`
- `systematic_equity.backtest_trade_blotter`

## 4. Where the current formal summaries already exist

The formal run already has a compact result summary and a human-readable report package.

Use:

- `team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report_summary.json`
- `team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report.md`
- `REFERENCE_STRATEGY_SUMMARY.md`

These already contain:

- formal run id
- pinned config path
- headline performance metrics
- row counts
- trade blotter hashes
- benchmark identifiers
- report-level artefacts and charts

## 5. Practical minimum to send

If the aim is that the recipient can understand both the definitions and the current formal results, the practical minimum is:

- the current GitHub branch / repository checkout
- `team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report.md`
- `team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report_summary.json`
- `team_Pearson/coursework_two/docs/strategy_design_decision_log_20260420.md`
- `team_Pearson/coursework_two/docs/formal_strategy_briefing_20260420.md`
- `team_Pearson/coursework_two/docs/research_upgrade_activeband_20260428.md`
- `team_Pearson/coursework_two/repro/reference_run_20260420.json`
- `REFERENCE_STRATEGY_SUMMARY.md`

If the aim is exact database-level replay or SQL-table inspection, also provide
a separately labelled release artifact for the formal run. Generated
`team_Pearson/coursework_two/outputs/handoff/` files are packaging outputs for
that purpose and are not required to be present in the Git checkout.

Historical qnative recovery assets should not be sent as the formal strategy
package.

## 6. Short conclusion

Code delivery answers the question of how the system works. Report and evidence
delivery answer what the current formal strategy produced and why that strategy
was selected. Optional external handoff artifacts answer the separate question
of exact frozen database-state restoration. The older frozen handoff assets
remain useful only where exact restoration of the historical qnative packaged
release is required.
