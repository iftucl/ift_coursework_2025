# Module Reference

## CW1 Core Runtime

| Module | Responsibility |
| --- | --- |
| `coursework_one/Main.py` | top-level upstream orchestration, stage execution, audit finalization |
| `modules/db/*` | engine creation and universe access |
| `modules/output/*` | normalize, quality, load, metadata, manifest, audit |
| `modules/transform/factors.py` | final-factor and rolling sentiment-related factor computation |
| `modules/transform/cw2_features.py` | PIT-clean snapshot assembly used by CW2 |

## CW1 Source Modules

| Module | Responsibility |
| --- | --- |
| `modules/input/extract_source_a.py` | Source A extraction and raw archive |
| `modules/input/extract_source_b.py` | AV historical + Finnhub incremental ingestion, MinIO merge state, sentiment and event-proxy atomics |
| `modules/extract/finnhub_news.py` | provider-specific Finnhub fetch path |
| `modules/utils/resilience.py` | circuit breaker, token bucket, retry helpers, Redis connectivity |
| `modules/utils/kafka.py` | Kafka config resolution, producer publishing, connectivity audit |

## CW2 Alpha and Portfolio Modules

| Module | Responsibility |
| --- | --- |
| `coursework_two/Main.py` | CW2 mode dispatch: features, operate, backtest, analyse, monitor, recommend, report, audit, and full-run |
| `modules/feature/factor_engine.py` | first-level factor score computation |
| `modules/feature/preprocessing.py` | winsorization, neutralization, and cross-sectional standardization |
| `modules/feature/composite_alpha.py` | regime-aware second-level alpha combination |
| `modules/portfolio/construction.py` | investable selection and constrained mean-variance weighting |
| `modules/risk/covariance.py` | statistical and fundamental-factor covariance estimation, ex-ante risk, and diagnostics |
| `modules/risk/actions.py` | formal risk-action contract |

## CW2 Backtest and Reporting Modules

| Module | Responsibility |
| --- | --- |
| `modules/backtest/engine.py` | stored-strategy backtest orchestration |
| `modules/backtest/execution.py` | transaction cost, slippage, liquidity clipping, cash ledger mechanics |
| `modules/backtest/intraday.py` | daily, weekly, and event-driven overlay logic |
| `modules/backtest/writer.py` | backtest SQL persistence and Kafka run/action publishing |
| `modules/analysis/*` | relative metrics, regime attribution, covariance diagnostics, scorecard |
| `modules/analysis/universe_benchmark.py` | gross same-universe equal-weight opportunity-set comparison (`universe_ew`) |
| `modules/analysis/static_baseline.py` | net-of-cost tradable construction-layer control (`static_baseline`) |
| `modules/reporting/report.py` | chart generation, markdown/json report packaging, artifact registry |
| `modules/recommendation/publisher.py` | recommendation publication, workflow events, approval/publish decisions |
| `modules/ops/audit.py` | end-to-end readiness audit across storage, history, and orchestration assumptions |
| `modules/ops/runtime_control.py` | Redis runtime locks, scheduler context snapshots, stage events, and quality recording |
| `modules/ops/monitoring.py` | SQL-backed pipeline/stage monitoring, ops event persistence, and health summaries |
| `modules/ops/kafka_audit.py` | Kafka consumer audit, lag snapshots, dead-letter capture, and reconciliation |
| `modules/ops/quality.py` | CW2-specific quality gate helpers layered on top of shared quality snapshots |

## Scheduler, Wrappers, and Docs Modules

| Module | Responsibility |
| --- | --- |
| `scripts/run_pipeline_and_index.py` | scheduler-safe wrapper around CW1 `Main.py` |
| `scripts/run_scheduled_pipeline.py` | Airflow-facing CW1 scheduling entrypoint |
| `coursework_two/scripts/run_full_chain.py` | one-command CW1 + CW2 full-workflow orchestration wrapper |
| `coursework_two/scripts/run_update_decision.py` | scheduler-safe daily CW2 decision wrapper |
| `coursework_two/scripts/run_operated_flow.py` | scheduler-safe CW2 operate wrapper |
| `coursework_two/scripts/run_backtest_analysis_report.py` | scheduler-safe CW2 research wrapper |
| `coursework_two/scripts/backfill_monthly_snapshots.py` | scheduler-safe CW2 monthly snapshot backfill wrapper |
| `coursework_two/scripts/run_readiness_audit.py` | explicit readiness gate wrapper for Airflow and local ops checks |
| `coursework_two/scripts/run_kafka_event_audit.py` | on-demand Kafka audit wrapper for scheduled reconciliation |
| `coursework_two/scripts/run_kafka_event_audit_daemon.py` | long-running Kafka audit consumer process |
| `scripts/build_sphinx_docs.py` | manual and automated Sphinx builder |
| `airflow/dags/cw1_pipeline_and_docs.py` | recurring daily Airflow DAG for upstream, docs, update decision, and gated operate |
| `airflow/dags/cw2_backtest_analysis_report.py` | scheduled monthly staged Airflow backtest/analyse/report/verify DAG |
| `airflow/dags/cw2_monthly_snapshot_backfill.py` | scheduled monthly Airflow snapshot-backfill plus audit DAG |
