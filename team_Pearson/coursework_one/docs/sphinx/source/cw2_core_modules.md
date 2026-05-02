# CW2 Core Modules

This page summarizes the current `CW2` production path at the module level.
It complements the higher-level architecture pages by showing which modules
own each stage, what they read, and what they persist.

## Current Control Path

The current formal control path is anchored by:

- `team_Pearson.coursework_two.Main`
- `team_Pearson.coursework_two.scripts.run_full_chain`
- `team_Pearson.coursework_two.scripts.run_backtest_analysis_report`

These entrypoints dispatch the current modes that matter operationally:

- feature generation and portfolio target production
- operate / update-decision / monitoring / recommendation workflows
- backtest, analysis, report, and verification bundles
- readiness audit and full-chain wrapper execution

## Alpha Generation Stack

The current alpha-generation path is:

1. `modules.portfolio.universe_screen.build_investable_universe`
2. `modules.feature.factor_engine.compute_factor_scores_for_date`
3. `modules.feature.composite_alpha.compute_composite_alpha`
4. `modules.risk.overlay.apply_risk_overlay`
5. `modules.portfolio.construction.build_portfolio_targets`

Key supporting modules in that path:

- `modules.feature.preprocessing` standardizes cross-sectional raw inputs before factor aggregation
- `modules.risk.covariance` provides statistical and fundamental-factor covariance estimation, ex-ante risk, and normalization helpers
- `modules.risk.actions` defines the formal risk-action contract used by downstream eventing

Current persistent outputs from this layer include:

- `feature_universe_screen`
- `feature_sub_scores`
- `feature_factor_scores`
- `feature_risk_overlay`
- `portfolio_target_positions`
- `portfolio_construction_diagnostics`
- `feature_snapshot_registry`
- `portfolio_snapshot_registry`
- `model_input_manifests`

## Research, Analysis, And Reporting Stack

The current research loop starts from stored portfolio targets rather than
recomputing signals inside the backtest.

Primary modules:

- `modules.backtest.engine.run_backtest_from_config`
- `modules.backtest.writer.*` SQL persistence and run lifecycle helpers
- `modules.analysis.relative_metrics.compute_relative_metrics`
- `modules.analysis.regime_attribution.compute_regime_attribution`
- `modules.analysis.covariance_risk.compute_covariance_diagnostics`
- `modules.analysis.scorecard.compute_scorecard`
- `modules.reporting.report.generate_backtest_report_from_config`

Current persistent outputs from this layer include:

- `backtest_runs`
- `backtest_holdings`
- `backtest_execution_ledger`
- `backtest_cash_ledger`
- `backtest_performance`
- `backtest_metrics`
- `backtest_benchmark_nav`
- `backtest_relative_metrics`
- `backtest_regime_attribution`
- `backtest_covariance_metrics`
- `backtest_covariance_contributions`
- `backtest_scorecard`
- report-registry rows and report artifacts under `coursework_two/outputs/reports/`

## Recommendation And Ops Stack

The current downstream operational layer is built around:

- `modules.recommendation.publisher`
- `modules.ops.audit`
- `modules.ops.runtime_control`
- `modules.ops.monitoring`
- `modules.ops.kafka_audit`
- `modules.utils.config_validation`

Their responsibilities are:

- publish and transition formal recommendation objects from stored targets
- validate the typed `CW2` config contract
- persist scheduler-stage context, runtime locks, and stage-quality evidence
- record SQL-backed pipeline/stage monitoring and Kafka audit state
- run read-only readiness checks across PostgreSQL, MinIO, MongoDB, Redis, and Kafka

Current persistent outputs from this layer include:

- `portfolio_update_decisions`
- `portfolio_recommendations`
- `portfolio_recommendation_items`
- `portfolio_recommendation_events`
- `portfolio_recommendation_decisions`
- `ops_pipeline_runs`
- `ops_stage_runs`
- `ops_event_log`
- `ops_kafka_consumer_ack`
- `ops_kafka_dead_letter`
- `ops_kafka_lag_snapshots`
- `ops_health_snapshots`
- `quality_snapshots`

## Current Documentation Boundary

The shared Sphinx site now exposes the current `CW2` project through four layers:

- narrative architecture and usage pages
- this module-level core map
- autodoc-backed API reference pages generated from module and function docstrings
- current live `CW2` runbook and current handoff reference included from `coursework_two/docs/`

For the frozen exact-metric GitHub-clone path, the authoritative reference
remains `team_Pearson/coursework_two/repro/README.md`.
