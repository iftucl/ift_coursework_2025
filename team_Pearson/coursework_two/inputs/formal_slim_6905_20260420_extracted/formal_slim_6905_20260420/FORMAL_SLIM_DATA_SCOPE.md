# Formal Slim Data Scope

## Baseline Identifiers

- Run id: `6905e84b-9e16-4106-8c0f-cd9ecce56728`
- Portfolio name: `cw2_formal_20260420_fund_ra3_s30_t50`
- Cutoff date: `2026-04-20`
- Target snapshots: 20
- Portfolio snapshot registry rows: 20
- Performance rows: 59
- Raw factor data included: yes
- Scenario outputs included: no; this package keeps only the formal baseline run and formal portfolio

## Included Source / Factor Data

- `company_static`
- `benchmark_prices`
- `factor_observations`
- `financial_observations`
- `dataset_registry`
- `source_coverage_audit`
- `quality_snapshots`

## Included Feature and Portfolio Construction Data

- `feature_factor_scores`
- `feature_sub_scores`
- `feature_universe_screen`
- `feature_risk_overlay`
- `feature_snapshot_registry`
- `model_input_manifests`
- `portfolio_target_positions` filtered to `cw2_formal_20260420_fund_ra3_s30_t50`
- `portfolio_snapshot_registry` filtered to `cw2_formal_20260420_fund_ra3_s30_t50`
- `portfolio_construction_diagnostics` filtered to `cw2_formal_20260420_fund_ra3_s30_t50`

## Included Baseline Backtest Outputs

Filtered to run id `6905e84b-9e16-4106-8c0f-cd9ecce56728`:

- `backtest_runs`
- `backtest_performance`
- `backtest_metrics`
- `backtest_holdings`
- `backtest_cash_ledger`
- `backtest_trade_blotter`
- `backtest_execution_ledger`
- `backtest_benchmark_nav`
- `backtest_benchmark_metrics`
- `backtest_relative_metrics`
- `backtest_factor_attribution`
- `backtest_covariance_metrics`
- `backtest_covariance_contributions`
- `backtest_regime_attribution`
- `backtest_scorecard`
- `backtest_reports`
- `backtest_report_artifacts`

## Excluded From This Slim Package

- Old `2026-04-24` reports
- Old `qnative_v2` runs
- Old sweep / microalpha / covariance test / mini-sweep outputs
- Old ablation outputs
- Old sensitivity outputs
- Old robustness reports
- Historical `outputs/report_assets`, old images, old PDFs, old CSV summaries
- `ops_*` operational logs
- Kafka ack/lag/dead-letter monitoring tables
- Old portfolio recommendations and recommendation events

## Caveat

This is a data package, not a runnable environment by itself. To rerun
robustness tests, the next owner also needs the current code repository and
Python/PostgreSQL environment.
