# Data Implementation

## Actual Runtime Behavior

The platform writes data into different stores by responsibility, not by duplication.

### Canonical storage split

- `MinIO`
  - raw provider payloads
  - replayable article snapshots
  - current-month merged Source B state
  - month-level cursor files

- `PostgreSQL`
  - curated factors and financial atomics
  - metadata and manifests
  - CW2 feature and portfolio tables
  - CW2 operational decision tables
  - CW2 control-plane and monitoring tables
  - recommendation workflow objects
  - backtest, analysis, and report registries

- `MongoDB`
  - rebuildable `news_articles` serving and search collection

- `Redis`
  - runtime-only resilience state
  - token buckets
  - circuit breakers
  - Source B dedupe keys
  - CW2 runtime locks, lock metadata, and heartbeat state

- `Kafka`
  - optional event fan-out
  - not the primary truth layer

## Source A

Current default runtime behavior:

- market history from `yfinance`
- fundamental supplement from `EDGAR XBRL`
- atomic outputs loaded into:
  - `factor_observations`
  - `financial_observations`

Archived Source A raw payloads now also carry:

- canonical `history[].observation_date`
- normalized OHLCV/dividend row fields
- `normalized_schema_version`
- `provider_payload_version`
- `schema_validation_status` and `schema_validation_errors`

## Source B

Current implementation is:

- `Alpha Vantage` for historical windows up to the configured cutoff
- `Finnhub` for post-cutoff incremental windows
- Loughran-McDonald sentiment scoring on the normalized article stream

### Raw layer

- `raw/source_b/news/run_date=.../year=.../month=.../symbol=...jsonl`
- `raw/source_b/news_current/year=.../month=.../symbol=...jsonl`
- `raw/source_b/news_cursor/year=.../month=.../symbol=...json`

Current normalized Source B raw objects also carry:

- canonical `publish_date` and `time_published`
- `time_precision` to distinguish full timestamps from date-only records
- `normalized_schema_version`
- `provider_payload_version`
- `schema_validation_status` and `schema_validation_errors`

### Curated daily atomics

- `news_sentiment_daily`
- `news_article_count_daily`

### Curated event proxies

- `earnings_news_count_daily`
- `earnings_negative_news_count_daily`
- `rating_downgrade_count_daily`
- `rating_upgrade_count_daily`

These are stored in `factor_observations` and can be consumed downstream by CW2.
All daily Source B atomics now also populate `publish_date` so news-derived
features follow the same PIT availability column used elsewhere in the platform.

## CW2 Feature and Portfolio Layer

CW2 materializes:

- investable universe screen
- first-level sub-scores
- first-level factor scores
- regime-aware risk overlay
- final `portfolio_target_positions`
- feature and portfolio snapshot registries
- model input manifests

This makes the monthly portfolio generation process auditable and replayable.

## CW2 Operational Decision Layer

CW2 also persists a daily operational decision table:

- `portfolio_update_decisions`

Each row classifies the current run date into one of:

- `monitor_only`
- `risk_review`
- `full_rebalance`
- `blocked`

This keeps incremental upstream refreshes, portfolio monitoring, and formal
rebalance runs separate in a way that can be audited from SQL.

## CW2 Control Plane Layer

CW2 also persists control-plane state in SQL through:

- `ops_pipeline_runs`
- `ops_stage_runs`
- `ops_event_log`
- `ops_kafka_consumer_ack`
- `ops_kafka_dead_letter`
- `ops_kafka_lag_snapshots`
- `ops_health_snapshots`
- `quality_snapshots`

These tables keep scheduler context, quality evidence, Kafka consumer audit, and
health snapshots queryable after the original process has finished.

## Recommendation Layer

CW2 now publishes formal recommendation objects:

- `portfolio_recommendations`
- `portfolio_recommendation_items`
- `portfolio_recommendation_events`
- `portfolio_recommendation_decisions`

These are the stored, approval-aware representation of end-user investment advice.

## Backtest, Analysis, and Reporting

Backtest outputs are stored in SQL, including:

- `backtest_runs`
- `backtest_holdings`
- `backtest_performance`
- `backtest_metrics`
- `backtest_cash_ledger`
- `backtest_intraday_events`
- `backtest_intraday_daily_state`

Analysis and reporting layers add:

- relative metrics
- regime attribution
- covariance diagnostics
- scorecard tables
- report artifact registries

## Kafka Eventing

When enabled, Kafka carries incremental events such as:

- structured news records from CW1
- daily event-proxy outputs from CW1
- requested risk actions from CW2
- executed risk actions from CW2
- run-status events

This layer is for **fan-out and decoupling**, not primary persistence.

## Airflow + Sphinx

Airflow currently orchestrates:

1. upstream pipeline execution
2. curated-data validation
3. Sphinx HTML build
4. daily CW2 update-decision run
5. month-end CW2 operate flow
6. scheduled monthly snapshot backfill plus post-backfill audit
7. scheduled monthly staged backtest/analyse/report/verify flow

Manual documentation build still uses:

```bash
python scripts/build_sphinx_docs.py --clean
```

The shared Sphinx source lives under `coursework_one/docs/sphinx/source`, but it
documents the combined `CW1 + CW2` platform.
