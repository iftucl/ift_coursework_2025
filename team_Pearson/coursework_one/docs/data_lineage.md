# Data Lineage

This document describes the implemented end-to-end data flow from source APIs to curated factors.

## 1. End-to-End Flow

1. Universe load:
- Read symbols from PostgreSQL `systematic_equity.company_static` (dynamic universe; fallback table `equity_static` if needed).
- Apply active include/exclude overrides from `systematic_equity.company_universe_overrides`.
- Optional country/symbol filtering policy is applied in extractor filters.

2. Source A (structured market/fundamentals):
- Primary provider: Alpha Vantage
- Fallback provider: yfinance
- Raw payload archived to MinIO:
  - `raw/source_a/pricing_fundamentals/run_date=YYYY-MM-DD/year=YYYY/symbol=XXX.json`
- Atomic rows produced into pipeline stream:
  - Market atomic (`adjusted_close_price`, `daily_return`, `dividend_per_share`) -> `factor_observations`
  - Financial atomic (`book_value`, `total_shareholder_equity`, `shares_outstanding`, `total_debt`, `enterprise_ebitda`, `enterprise_revenue`) -> `financial_observations`

3. Source B (unstructured news text):
- Alpha Vantage `NEWS_SENTIMENT` is used for article text ingestion.
- Raw payload archived to MinIO as JSONL (symbol x month):
  - `raw/source_b/news/run_date=YYYY-MM-DD/year=YYYY/month=MM/symbol=XXX.jsonl`
- Current-month merged view:
  - `raw/source_b/news_current/year=YYYY/month=MM/symbol=XXX.jsonl`
- Incremental cursor metadata:
  - `raw/source_b/news_cursor/year=YYYY/month=MM/symbol=XXX.json`
- Deduplication rule: URL first, fallback to `title+time_published`.
- Alternative atomic rows:
  - `news_sentiment_daily` (daily sentiment)
  - `news_article_count_daily` (daily article count)

4. Normalize + quality + load:
- Records are normalized to long-table schema.
- Quality checks validate required columns, frequency values, duplicates, and finite numeric values.
- Upsert market/alternative atomic + final factors into `systematic_equity.factor_observations` via unique constraint (`symbol`, `observation_date`, `factor_name`).
- Upsert financial atomic into `systematic_equity.financial_observations` via unique constraint (`symbol`, `report_date`, `metric_name`).

5. Final-factor transform stage:
- Read market/alternative atomic from `factor_observations` and financial atomic from `financial_observations`.
- Compute final factors in `modules/transform/factors.py` (including recomputed technical daily factors `momentum_1m` and `volatility_20d` from `adjusted_close_price`).
- Write final factors back to `factor_observations`.

6. Audit:
- Primary run audit written to PostgreSQL `systematic_equity.pipeline_runs`.
- Secondary local mirror written to `logs/pipeline_runs.jsonl`.

7. Mongo index stage (default, best-effort):
- Triggered by `Main.py` after core pipeline status is `success`.
- Builds/updates Mongo search collection `ift_cw.news_articles` by running `scripts/index_news_to_mongo.py`.
- Disable explicitly with `--no-index-mongo`; `--dry-run` skips this stage.
- Failure mode is warning-only (core SQL pipeline success state is preserved).

## 2. Factor-Level Lineage

| Final Factor | Atomic Inputs | Core Rule | Output |
| --- | --- | --- | --- |
| `dividend_yield` | `dividend_per_share`, `adjusted_close_price` | daily as-of: TTM DPS / backward-looking price (max 3 trading-day lookback) | `factor_observations` |
| `pb_ratio` | `adjusted_close_price`, `shares_outstanding`, `total_shareholder_equity` | `(price * shares) / total_shareholder_equity`, positive checks, monthly cross-sectional cap at 99th percentile (fallback `100.0` when month sample size < `50`), max 3 trading-day lookback (`flag_stale_price=True` warning if fallback >1 trading day), financial staleness: soft `(270,365]` warning / hard `>365` drop | `factor_observations` |
| `debt_to_equity` | `total_debt`, `total_shareholder_equity` | `total_debt / total_shareholder_equity`; atomics update quarterly, factor is expanded daily as-of (stepwise) for backtest alignment; financial staleness: soft `(270,365]` warning / hard `>365` drop | `factor_observations` |
| `momentum_1m` | `adjusted_close_price` | `price / price.shift(20) - 1` (daily) | `factor_observations` |
| `volatility_20d` | `adjusted_close_price` | `std(pct_change(price), rolling 20)` (daily) | `factor_observations` |
| `ebitda_margin` | `enterprise_ebitda`, `enterprise_revenue` | `ebitda / revenue`, revenue must be positive, financial staleness: soft `(270,365]` warning / hard `>365` drop | `factor_observations` |
| `sentiment_30d_avg` | `news_sentiment_daily` | daily mean->fill missing dates with `0.0`->rolling `30D` mean, capped `[-1,1]` | `factor_observations` |
| `article_count_30d` | `news_article_count_daily` | daily count->fill missing dates with `0.0`->rolling `30D` sum | `factor_observations` |

## 3. Storage and Partitioning

MinIO raw layer:
- Source A: one object per `symbol x run_date`.
- Source B:
  - run snapshots: one object per `symbol x month` under each run date
  - current merged month view: one object per `symbol x month`
  - cursor metadata: one object per `symbol x month`

PostgreSQL curated layer:
- Layered long tables:
  - `systematic_equity.factor_observations` (market/alternative atomic + final factors)
  - `systematic_equity.financial_observations` (financial atomic)
- Query optimized by:
  - symbol index
  - date indexes (`observation_date` / `report_date`)
  - unique business keys by table

Mongo serving/index layer:
- Collection: `ift_cw.news_articles`
- Canonical symbol field: `symbols`
- Compatibility alias: `tickers`
- Primary search/index path:
  - text index on `title + summary`
  - filter/sort via `symbols` and `time_published`
- Document-level raw trace:
  - `minio_object_keys` links each indexed document back to MinIO source objects

## 4. Reproducibility Notes

- `run_date`, `frequency`, `backfill_years`, `company_limit`, and `enabled_extractors` are recorded in `pipeline_runs`.
- Raw payloads in MinIO include `run_date` in path to support replay/audit.
- Idempotent upsert prevents duplicate factor rows across repeated runs for the same business key.
- Final factors are first built at daily granularity, then optionally sampled by output frequency (`daily/weekly/monthly/quarterly/annual`).
