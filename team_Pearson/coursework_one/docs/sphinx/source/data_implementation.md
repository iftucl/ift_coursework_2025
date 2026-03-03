# Data Implementation

## Scope

This page describes what the current code actually does for extraction, normalization, loading, and factor generation.

Authoritative code paths:
- `Main.py`
- `modules/input/extract_source_a.py`
- `modules/input/extract_source_b.py`
- `modules/output/normalize.py`
- `modules/output/quality.py`
- `modules/output/load.py`
- `modules/transform/factors.py`
- `sql/init.sql`

## 1. Runtime Flow

Pipeline execution in `Main.py`:

1. Resolve runtime config (`run_date`, `frequency`, `backfill_years`, enabled extractors).
2. Load universe from `systematic_equity.company_static`.
3. Extract atomics from Source A and Source B.
4. Split records:
   - financial atomics -> `financial_observations`
   - other atomics/factors -> `factor_observations`
5. Normalize and run quality checks.
6. Upsert curated atomics into PostgreSQL.
7. Build final factors from atomics and upsert back to `factor_observations`.

## 2. Frequency Model

| Layer | Current behavior |
| --- | --- |
| Pipeline run cadence | Usually daily (scheduler default), configurable |
| Atomic collection call | Invoked with `daily` runtime cadence |
| Source A semantic cadence | Market/news-like fields daily; financial fields filing-period based |
| Source B fetch cadence | Month-window incremental fetch with lookback buffer |
| Final factor output cadence | Daily compute first, then sample by `--frequency` |

Key clarification:
- `--frequency` controls final-factor sampling only.
- It does not change extractor fetch cadence.

## 3. Storage Contract

### 3.0 Main.py direct write scope

`Main.py` directly writes to:
- PostgreSQL:
  - `systematic_equity.factor_observations`
  - `systematic_equity.financial_observations`
  - `systematic_equity.pipeline_runs`
- MinIO:
  - Source A / Source B raw snapshots
  - Source B cursor objects
  - Source B current-month merged objects

`Main.py` does not directly write MongoDB.

### 3.1 PostgreSQL curated tables

| Table | Key | Notes |
| --- | --- | --- |
| `systematic_equity.factor_observations` | `(symbol, observation_date, factor_name)` | final factors + non-financial atomics; `metric_value` as `NUMERIC(18,6)` |
| `systematic_equity.financial_observations` | `(symbol, report_date, metric_name)` | filing-period financial atomics with `period_type`, `as_of`, `currency` |
| `systematic_equity.pipeline_runs` | `run_id` | run lifecycle audit (`running/success/failed`) |

### 3.2 MinIO raw layer

- Source A: `raw/source_a/pricing_fundamentals/...`
- Source B snapshots: `raw/source_b/news/run_date=.../year=.../month=.../symbol=...jsonl`
- Source B cursor: `raw/source_b/news_cursor/year=.../month=.../symbol=...json`
- Source B month-current merged view: `raw/source_b/news_current/...`

### 3.3 MongoDB search index

- Collection: `ift_cw.news_articles`
- Canonical fields: `time_published`, `tickers`
- Compatibility aliases: `published_at`, `symbols`
- Enabled by default in scheduler/orchestrator scripts; disable with `--no-index-mongo`.
- `Main.py` does not directly index MongoDB.

Mongo responsibility split:
- `Main.py` is the core ETL path (extract -> normalize -> PostgreSQL load, with raw MinIO archive).
- MongoDB indexing is a serving/search layer executed after a successful main run by:
  - `scripts/run_pipeline_and_index.py`
  - `scripts/run_scheduled_pipeline.py`
- This keeps core factor loading independent from search-index availability.

## 4. Metric Definitions

### 4.1 Atomic metrics

| Metric | Source cadence | Stored cadence | Meaning / Formula | Key rules |
| --- | --- | --- | --- | --- |
| `adjusted_close_price` | daily market trading | daily | adjusted close | provider-aligned daily row |
| `daily_return` | daily market trading | daily | `ln(P_t/P_{t-1})` | null if current/previous price invalid |
| `dividend_per_share` | daily market series | daily | provider dividend amount | mostly `0`, non-zero on dividend dates |
| `total_debt` | quarterly filings | quarterly snapshot | provider debt | in `financial_observations` |
| `total_shareholder_equity` | quarterly filings | quarterly snapshot | provider equity | in `financial_observations` |
| `book_value` | quarterly filings | quarterly snapshot | provider/derived book value | in `financial_observations` |
| `shares_outstanding` | quarterly filings | quarterly snapshot | provider shares outstanding | in `financial_observations` |
| `enterprise_ebitda` | quarterly filings | quarterly snapshot | provider EBITDA field | in `financial_observations` |
| `enterprise_revenue` | quarterly filings | quarterly snapshot | provider revenue field | in `financial_observations` |
| `news_sentiment_daily` | daily news flow | daily | daily mean sentiment score | score clipped to `[-1,1]` |
| `news_article_count_daily` | daily news flow | daily | daily article count | non-negative |

### 4.2 Final factors

| Metric | Input cadence | Output cadence | Meaning / Formula | Key rules |
| --- | --- | --- | --- | --- |
| `momentum_1m` | daily prices | daily (then sampled) | `close/close.shift(20)-1` | requires enough history |
| `volatility_20d` | daily prices | daily (then sampled) | rolling 20-day std of returns | requires enough history |
| `dividend_yield` | daily price + dividend | daily as-of | trailing 365-day DPS sum / price | price lookback <= 3 trading days |
| `pb_ratio` | filing metrics + daily price | daily as-of | `(price*shares_outstanding)/equity` | stale/expire rule + per-symbol winsor |
| `debt_to_equity` | filing metrics | daily as-of | `debt/equity` | stale/expire rule; equity > 0 |
| `ebitda_margin` | filing metrics | daily as-of | `ebitda/revenue` | stale/expire rule; revenue > 0 |
| `sentiment_30d_avg` | `atomic_news` daily | daily (then sampled) | rolling `30D` mean sentiment | no-news calendar days are zero-filled |
| `article_count_30d` | `atomic_news` daily | daily (then sampled) | rolling `30D` sum count | no-news calendar days are zero-filled; not a direct trading signal in current strategy |

## 5. Quality and Missing-Value Rules

### 5.1 Global rules

- Rows missing any of `observation_date`, `symbol`, `factor_name` are dropped.
- Invalid timestamps are dropped during normalization.
- Non-finite numeric values are filtered/flagged before load.
- DB loaders use upsert semantics for idempotent reruns.

### 5.2 Financial staleness and validity

- Stale warning: age > `270` days.
- Hard expire drop: age > `365` days.
- Applied in as-of selection for `pb_ratio`, `debt_to_equity`, `ebitda_margin`.
- Numeric coercion (`to_numeric(..., errors="coerce")`) is applied before ratio computation.
- Rows are skipped for invalid denominator or missing required values.

### 5.3 Price lookback guard

For `dividend_yield` and `pb_ratio`:
- use exact-day price first;
- fallback to at most 3 prior trading records;
- require price `>0`, otherwise skip.

### 5.4 Sentiment chain (Source B)

- Fetch loop is month-window based with incremental start/end windows.
- Incremental buffer is controlled by `SOURCE_B_INCREMENTAL_BUFFER_DAYS` (default `3`).
- Cursor is per `symbol + year-month` with fields `last_ingested_date` and `is_closed`.
- Closed months are skipped in daily runs to avoid repeated re-fetch.
- Missing article timestamp fallback uses `fetch_start` (then `month_start`, then legacy `month_end`), not `fetch_end`.
- Daily atomics are built first, then 30-day rolling factors after calendar-day zero-fill.

## 6. Validation Coverage

`scripts/validate_pipeline_data.py` checks:
- duplicate key rows
- required-field completeness
- invalid frequency/source labels
- `daily_return` recomputation consistency
- `debt_to_equity` recomputation consistency
- sentiment null/negative constraints
- optional coverage-gap checks

Minimal replay check:

```bash
poetry run pytest -q -o addopts='' tests/test_replay_regression.py
```

This replay check is advisory (non-blocking) by design.

## 7. Implementation Notes

- Financial atomics are stored in `financial_observations` with filing-period semantics.
- Final factors are produced daily first, then sampled to requested output frequency.
- `NUMERIC(18,6)` storage can introduce small rounding differences.
