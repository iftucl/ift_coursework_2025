# Architecture Overview

## Platform Scope

The implemented platform is no longer only a `CW1` ETL skeleton. It is now a
**full pipeline from data collection to portfolio recommendation, backtest reporting, and exact-run reproducibility**.

The platform is split into two logical domains:

1. `CW1`
   - upstream ingestion
   - raw archival
   - normalization
   - curated factor and financial atomics
   - metadata, manifests, and audit

2. `CW2`
   - first-level factor scoring
   - second-level composite alpha
   - regime-aware portfolio construction
   - recommendation workflow
   - backtest, analysis, and reporting
   - daily/weekly/event-driven risk overlay

## Runtime Topology

The current production-style runtime has eight operational layers:

1. ingestion
   - `source_a`: `yfinance` market history plus `EDGAR XBRL`
   - `source_b`: `Alpha Vantage` historical news plus `Finnhub` incremental news

2. resilience
   - Redis-backed circuit breakers
   - Redis-backed token buckets
   - Redis-backed per-symbol Source B URL dedupe

3. storage
   - `MinIO` for raw and replayable objects
   - `PostgreSQL` for curated truth, portfolio state, backtests, analysis, reporting, and audit
   - `MongoDB` for rebuildable news search and serving

4. control plane
   - SQL-backed `ops_pipeline_runs` and `ops_stage_runs`
   - stage-level `quality_snapshots`
   - Redis-backed runtime locks, heartbeat refresh, and stale-lock recovery

5. eventing
   - `Kafka` for structured-news fan-out, event proxies, requested risk actions,
     executed risk actions, and run-status events

6. portfolio intelligence
   - `CW2` first-level factors
   - regime-aware second-level composite alpha
   - hybrid selection and long-only constrained mean-variance weighting with
     the formal factor covariance risk model
   - daily risk overlay and event-driven actions

7. orchestration
   - `Main.py` entrypoints for `CW1` and `CW2`
   - scheduler-safe wrappers and Airflow DAGs for recurring and monthly orchestration

8. documentation and reproducibility
   - shared Sphinx source in `docs/sphinx/source`
   - manual build via `scripts/build_sphinx_docs.py`
   - automated build through Airflow
   - frozen CW2 release bundle and reference verification under `coursework_two/repro/`

## Source B Design

Source B follows a single unified pipeline:

1. route by date:
   - if the window is on or before the configured cutoff, use `Alpha Vantage`
   - if the window is after the cutoff, use `Finnhub`
   - if the window crosses the cutoff, split the window and deduplicate the combined result
2. normalize provider payloads to one article schema
3. archive raw JSONL to `MinIO`
4. maintain current-month merged state and per-month cursor files
5. score article text with the Loughran-McDonald lexicon
6. emit daily atomics such as:
   - `news_sentiment_daily`
   - `news_article_count_daily`
   - `earnings_news_count_daily`
   - `earnings_negative_news_count_daily`
   - `rating_downgrade_count_daily`
   - `rating_upgrade_count_daily`
7. optionally fan out structured article and event-proxy messages to `Kafka`

## CW2 Strategy Design

CW2 uses a layered portfolio process:

1. preprocess and neutralize the cross section
2. compute first-level factors:
   - `quality`
   - `value`
   - `market_technical`
   - `sentiment`
   - `dividend`
3. combine them into regime-aware `composite_alpha`
4. apply risk overlay screens
5. select the final investable set
6. allocate weights with constrained `mean_variance` using the configured
   `fundamental_factor` covariance model
7. publish a formal recommendation object
8. run a database-backed backtest with:
   - transaction costs
   - slippage
   - ADV participation limits
   - liquidity clipping
   - cash ledger
   - daily/weekly/event-driven risk actions

The shared factor framework keeps a `sentiment` group in the formal CW2
architecture. In the current formal configuration it receives `0.00` weight in
the normal regime and `0.05` weight in the stress regime, so it should be
described as stored and supported, but only lightly active under stress.

## Scheduling Design

Airflow owns the orchestrated path:

1. `cw1_pipeline_and_docs`
   - `run_daily_pipeline`
   - `validate_curated_data`
   - `build_sphinx_docs`
   - `run_cw2_update_decision`
   - `check_cw2_operate_rebalance_anchor`
   - `run_cw2_operate_on_rebalance_anchor`

2. `cw2_monthly_snapshot_backfill`
   - `backfill_monthly_snapshots`
   - `run_post_backfill_readiness_audit`
   - `audit_kafka_event_bus`
   - `cleanup_stage_context`

3. `cw2_backtest_analysis_report`
   - `run_preflight_readiness_audit`
   - `run_backtest_stage`
   - `run_analysis_stage`
   - `run_report_stage`
   - `verify_reference_contract`
   - `audit_kafka_event_bus`
   - `cleanup_stage_context`

This keeps scheduled ingestion, portfolio operations, reporting, and documentation
inside one controlled operational layer, while the frozen release bundle keeps a
separate exact-reproduction contract for the formal CW2 run.
