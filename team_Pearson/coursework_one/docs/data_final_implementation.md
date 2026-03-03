# Data Final Implementation (Code-Aligned)

This document is a single-source summary of what the current code actually does.

Authoritative code paths:
- `Main.py`
- `modules/input/extract_source_a.py`
- `modules/input/extract_source_b.py`
- `modules/output/normalize.py`
- `modules/output/quality.py`
- `modules/output/load.py`
- `modules/transform/factors.py`
- `sql/init.sql`

---

## 1. Runtime Flow

Pipeline execution in `Main.py`:

1. Resolve runtime args/config (`run_date`, `frequency`, `backfill_years`, extractors).
2. Load universe from `systematic_equity.company_static`.
3. Extract atomics from Source A and Source B.
4. Split records:
   - financial atomics -> `financial_observations`
   - other atomics/factors -> `factor_observations`
5. Normalize and quality-check records.
6. Upsert curated/financial atomics into PostgreSQL.
7. Build final factors from atomics and upsert back to `factor_observations`.

Operational note:
- atomic extraction is called with daily cadence (`collect_raw_records(..., "daily", ...)`)
- output sampling supports `daily/weekly/monthly/quarterly/annual`

---

## 2. Storage Contract

## 2.1 PostgreSQL curated factors
- Table: `systematic_equity.factor_observations`
- Unique key: `(symbol, observation_date, factor_name)`
- Value type: `NUMERIC(18,6)`
- `metric_frequency`: `daily/weekly/monthly/quarterly/annual/unknown`

## 2.2 PostgreSQL financial atomics
- Table: `systematic_equity.financial_observations`
- Unique key: `(symbol, report_date, metric_name)`
- Fields include: `metric_value`, `currency`, `period_type`, `as_of`, `metric_definition`

## 2.3 Raw layer (MinIO)
- Source A: `raw/source_a/pricing_fundamentals/...`
- Source B: `raw/source_b/news/run_date=.../year=.../month=.../symbol=...jsonl`
- Source B incremental cursor: `raw/source_b/news_cursor/year=.../month=.../symbol=...json`

## 2.4 Search layer (MongoDB)
- Collection: `ift_cw.news_articles`
- Canonical fields: `time_published`, `tickers`
- Compatibility aliases: `published_at`, `symbols`
- Scheduler/orchestrator scripts enable Mongo indexing by default; disable with `--no-index-mongo`.

---

## 3. Metrics, Meaning, and Cadence

Cadence definitions:
- `source cadence`: natural upstream update rhythm
- `output cadence`: what this code writes
- `run cadence`: how often pipeline is triggered (default daily, configurable)

Run cadence note:
- all metrics in this table are produced when the pipeline runs; run cadence is controlled globally by runtime args/config (default daily).

| Metric | Source cadence | Output cadence | Meaning / Formula | Key rules |
| --- | --- | --- | --- | --- |
| `adjusted_close_price` | daily market trading | daily | adjusted close | raw market atomic |
| `daily_return` | daily market trading | daily | `ln(P_t/P_{t-1})` | null when invalid/missing `P_t` or `P_{t-1}` |
| `dividend_per_share` | daily market series (mostly 0; non-zero on dividend dates) | daily stream | provider dividend amount from daily price history row | raw market atomic |
| `total_debt` | quarterly filings | stored in financial atomics | provider-reported debt | financial atomic |
| `total_shareholder_equity` | quarterly filings | stored in financial atomics | provider-reported equity | financial atomic |
| `book_value` | quarterly filings | stored in financial atomics | provider/derived book value | stored as `NUMERIC(18,6)` |
| `shares_outstanding` | quarterly filings | stored in financial atomics | provider-reported shares | financial atomic |
| `enterprise_ebitda` | quarterly filings | stored in financial atomics | provider EBITDA field | financial atomic |
| `enterprise_revenue` | quarterly filings | stored in financial atomics | provider revenue field | financial atomic |
| `momentum_1m` | from daily prices | daily | `close/close.shift(20)-1` | 20-trading-day lag |
| `volatility_20d` | from daily prices | daily | rolling 20-day std of returns | requires enough history |
| `dividend_yield` | dividends + price | daily as-of | trailing 365-day DPS sum / price | price lookback <= 3 trading days |
| `pb_ratio` | filings + price | daily as-of | `(price*shares_outstanding)/total_shareholder_equity` | per-symbol 252-bday rolling winsor, staleness 270/365 |
| `debt_to_equity` | filings | daily as-of | `total_debt/total_shareholder_equity` | staleness 270/365, equity > 0 |
| `ebitda_margin` | filings | daily as-of | `enterprise_ebitda/enterprise_revenue` | staleness 270/365, revenue > 0 |
| `news_sentiment_daily` | daily news flow | daily | article sentiment daily mean | score clipped to `[-1,1]` |
| `news_article_count_daily` | daily news flow | daily | daily article count | non-negative count |
| `sentiment_30d_avg` | from news atomics | daily | rolling `30D` mean of daily sentiment | no-news days zero-filled |
| `article_count_30d` | from news atomics | daily | rolling `30D` sum of daily counts | no-news days zero-filled |

---

## 4. Quality Rules Actually Enforced

Common normalization and load:
- invalid `observation_date` rows are dropped during normalization
- required fields checked: `symbol`, `observation_date`, `factor_name`, `source`, `metric_frequency`
- non-finite numeric values are flagged
- DB load uses upsert semantics (idempotent reruns)

Financial staleness (transform):
- soft stale warning: age > `270` days
- hard expire drop: age > `365` days
- applied to `pb_ratio`, `debt_to_equity`, `ebitda_margin` via latest-as-of selection

Price lookback:
- `dividend_yield` and `pb_ratio` use strict backward-only price lookup
- exact day preferred; fallback up to 3 prior trading records
- dropped when no valid positive price found

PB winsorization (exact current logic):
- build daily `pb_ratio` rows first
- split by `symbol`
- for each `symbol` and day `t`, use trailing business-day window
  (default `252`, env `PB_WINSOR_LOOKBACK_BDAYS`)
- if per-symbol window sample >= `50`: cap at rolling `q99`
- else: fallback cap `100.0`

Sentiment-specific (implemented):
- default timestamp policy may fallback missing article time to a default date
- strict mode (`source_b.strict_time=true`) drops missing-time rows
- rolling `30D` signals are built after calendar-day zero-fill
- Source B ingestion uses incremental fetch with lookback buffer (`SOURCE_B_INCREMENTAL_BUFFER_DAYS`, default `3`)
- cursor key is per `symbol + year-month`, stored as `raw/source_b/news_cursor/.../symbol=...json`
- cursor field: `last_ingested_date` (ISO date)
- fetch window each run:
  - `fetch_start = month_start` when cursor missing
  - otherwise `fetch_start = max(month_start, last_ingested_date - buffer_days)`
  - `fetch_end = min(month_end, run_date)`
- raw snapshots remain partitioned by `run_date` under `raw/source_b/news/...` for replay/audit traceability

### 4.1 Missing-Value and Validity Handling (Code-Aligned)

The rules below match the current implementation in `modules/transform/factors.py`.

1. `dividend_yield`
- `price` and `dps` are converted via `pd.to_numeric(..., errors="coerce")`; invalid values become `NaN`.
- Days with missing or `<=0` price are skipped (price lookup only returns valid positive prices).
- Missing dividends are treated as `0` in TTM (365-day) summation using `fillna(0.0)`.
- Reference functions: `_compute_dividend_yield_daily_asof`, `_find_price_row_with_trading_day_lookback`.

2. `pb_ratio`
- `price`, `shares`, and `equity` all use numeric coercion; any non-numeric, missing, or `<=0` input is skipped.
- Financial recency policy: `>365` days is expired and dropped; `270~365` days is marked stale but still usable.
- Reference functions: `_compute_pb_ratio_daily_asof`, `_latest_financial_with_staleness_logging`.

3. `debt_to_equity`
- `debt` and `equity` use numeric coercion; rows are skipped when `equity<=0` or missing.
- Uses the same `270/365` stale/expire financial recency policy.
- Reference functions: `_compute_debt_to_equity_daily_asof`, `_latest_financial_with_staleness_logging`.

4. `ebitda_margin`
- `ebitda` and `revenue` use numeric coercion; rows are skipped when `revenue<=0` or missing.
- Uses the same `270/365` stale/expire financial recency policy.
- Reference functions: `_compute_ebitda_margin`, `_latest_financial_with_staleness_logging`.

5. `momentum_1m` / `volatility_20d`
- Price rows with missing values or `price<=0` are removed first; if history has fewer than 20 rows, no output is produced.
- After computation, series are `dropna()` first, then `_to_float_or_none` filters `NaN/Inf`.
- Reference functions: `_compute_technical_factors_daily`, `_to_float_or_none`.

6. `sentiment_30d_avg` / `article_count_30d`
- For `news_article_count_daily`: invalid dates are filtered after `to_datetime(..., errors="coerce")`; failed numeric conversion is filled with `0` during daily reindexing.
- Calendar days with no news are explicitly zero-filled (`sentiment=0`, `article_count=0`) before `30D` rolling.
- For `news_sentiment_daily`: invalid numeric values or invalid dates are removed via `dropna(subset=["sentiment", "observation_ts"])`.
- Reference function: `_compute_sentiment_30d_avg`.

Two additional global filters:
- Atomic input record level: rows with missing `observation_date`, `symbol`, or `factor_name` are dropped.
- Price lookback layer (used by `dividend_yield`, `pb_ratio`): only up to 3 prior trading days are allowed, and price must be `>0` (with an extra business-day gap guard).
- Reference functions: `compute_final_factor_records`, `_find_price_row_with_trading_day_lookback`.

---

## 5. Validation Coverage

`scripts/validate_pipeline_data.py` checks:
- duplicate key rows
- missing required fields
- invalid frequency/source labels
- `daily_return` recomputation consistency
- `debt_to_equity` recomputation consistency
- sentiment/count null/negative checks
- optional coverage-gap checks for selected factors

### 5.1 Minimal Non-Blocking Replay Check (Solo Workflow)

To keep merge flow simple while still guarding the
`extract -> transform -> final factors` chain, run one manual check before merging:

```bash
poetry run pytest -q -o addopts='' tests/test_replay_regression.py
```

Policy:
- This check is advisory (non-blocking), not a required GitHub status check.
- If it fails but you still merge, record one short reason in the PR/commit note.

---

## 6. Implementation Notes

- Financial atomics are persisted in `financial_observations` (not only in factor table).
- Mongo search layer keeps provider-aligned array field `tickers` (with alias `symbols`).
- `NUMERIC(18,6)` introduces small rounding differences (for example `book_value`).
