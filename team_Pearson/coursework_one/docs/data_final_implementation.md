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
- atomic collection currently runs with daily cadence in the main pipeline (`collect_raw_records` runtime path).
- this does not force all atomics to daily semantics (financial atomics remain filing-period based), and `output_frequency` only controls final-factor sampling.

| Metric | Source cadence | Output cadence | Meaning / Formula | Key rules |
| --- | --- | --- | --- | --- |
| `adjusted_close_price` | daily market trading | daily | adjusted close price | `atomic_market`; provider-aligned daily row |
| `daily_return` | daily market trading | daily | `ln(P_t/P_{t-1})` | `atomic_market`; null when invalid/missing `P_t` or `P_{t-1}` |
| `dividend_per_share` | daily market series (mostly 0; non-zero on dividend dates) | daily | provider dividend amount from daily price history row | `atomic_market`; provider-aligned daily row |
| `total_debt` | quarterly filings | quarterly snapshot in `financial_observations` | provider-reported debt | `atomic_financial`; keyed by `symbol+report_date+metric_name` |
| `total_shareholder_equity` | quarterly filings | quarterly snapshot in `financial_observations` | provider-reported equity | `atomic_financial`; keyed by `symbol+report_date+metric_name` |
| `book_value` | quarterly filings | quarterly snapshot in `financial_observations` | provider/derived book value | `atomic_financial`; stored as `NUMERIC(18,6)` |
| `shares_outstanding` | quarterly filings | quarterly snapshot in `financial_observations` | provider-reported shares | `atomic_financial`; keyed by `symbol+report_date+metric_name` |
| `enterprise_ebitda` | quarterly filings | quarterly snapshot in `financial_observations` | provider EBITDA field | `atomic_financial`; keyed by `symbol+report_date+metric_name` |
| `enterprise_revenue` | quarterly filings | quarterly snapshot in `financial_observations` | provider revenue field | `atomic_financial`; keyed by `symbol+report_date+metric_name` |
| `momentum_1m` | derived from daily prices | daily | `close/close.shift(20)-1` | `final_factor`; requires enough price history |
| `volatility_20d` | derived from daily prices | daily | rolling 20-day std of returns | `final_factor`; requires enough price history |
| `dividend_yield` | derived from dividends + prices | daily as-of | trailing 365-day DPS sum / price | `final_factor`; price lookback <= 3 trading days |
| `pb_ratio` | derived from filings + prices | daily as-of | `(price*shares_outstanding)/total_shareholder_equity` | `final_factor`; per-symbol 252-bday rolling winsor + staleness 270/365 |
| `debt_to_equity` | derived from filings | daily as-of | `total_debt/total_shareholder_equity` | `final_factor`; staleness 270/365, equity > 0 |
| `ebitda_margin` | derived from filings | daily as-of | `enterprise_ebitda/enterprise_revenue` | `final_factor`; staleness 270/365, revenue > 0 |
| `news_sentiment_daily` | daily news flow | daily | daily mean sentiment score from article text | `atomic_news`; score clipped to `[-1,1]` |
| `news_article_count_daily` | daily news flow | daily | daily article count | `atomic_news`; non-negative count |
| `sentiment_30d_avg` | derived from `atomic_news` | daily | rolling `30D` mean of daily sentiment | `final_factor`; no-news calendar days zero-filled |
| `article_count_30d` | derived from `atomic_news` | daily | rolling `30D` sum of daily counts | `final_factor`; no-news calendar days zero-filled; not used as a direct trading signal in the current strategy |

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
- Source B extraction scheduling is month-window based, but not full historical re-fetch on every run:
  - runs iterate month windows in the backfill horizon
  - open months use incremental `fetch_start/fetch_end`
  - closed months (`is_closed=true`) are skipped
- default timestamp policy may fallback missing article time to a default date
- strict mode (`source_b.strict_time=true`) drops missing-time rows
- rolling `30D` signals are built after calendar-day zero-fill
- Source B ingestion uses incremental fetch with lookback buffer (`SOURCE_B_INCREMENTAL_BUFFER_DAYS`, default `3`)
- cursor key is per `symbol + year-month`, stored as `raw/source_b/news_cursor/.../symbol=...json`
- cursor fields: `last_ingested_date` (ISO date) and `is_closed` (bool)
- fetch window each run:
  - `fetch_start = month_start` when cursor missing
  - for the first backfill month with no cursor, `fetch_start = max(month_start, backfill_start_date)`
  - otherwise `fetch_start = max(month_start, last_ingested_date - buffer_days)`
  - `fetch_end = min(month_end, run_date)`
- month-close freeze:
  - when `last_ingested_date >= month_end`, cursor is saved with `is_closed=true`
  - subsequent daily runs skip closed months (no repeated buffer re-fetch)
- merged month-current view:
  - current-month merged view is stored under `raw/source_b/news_current/...`
  - each run merges newly fetched records with existing month records using dedupe+overwrite
  - run snapshots under `raw/source_b/news/run_date=...` are still preserved for replay/audit
- missing-time fallback uses `fetch_start` (then `month_start`, then legacy `month_end`) instead of `fetch_end`
- transformed atomic outputs remain daily (`news_sentiment_daily`, `news_article_count_daily`)
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
