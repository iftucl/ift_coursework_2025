# Data Requirements Log
**Strategy:** Quality, Dividend & Sentiment Composite Strategy
**History Requirement:** Minimum 5 years backfill
**Query Requirement:** Must support retrieval by company and by year

---

## 1. `dividend_yield` (Dividend Yield)

| Field | Specification |
|------|--------------|
| Metric Name (code) | `dividend_yield` |
| Raw Fields | `dividend_per_share`, `adjusted_close_price` |
| Origin Source (Input) | Source A atomics (Alpha Vantage primary, yfinance fallback) |
| Target Storage (Output) | PostgreSQL (`systematic_equity.factor_observations`) |
| Frequency | Daily as-of computation (then sampled by pipeline output frequency) |
| History | ≥ 5 years |
| Calculation Logic | `dividend_yield = trailing_12m_dps / price` |

### Missing / Error Tolerance & Quality Rules
- **Look-ahead Bias Prevention:** price lookup is strictly backward-looking, with at most 3 prior trading days.
- **Missing DPS Tolerance:** trailing 12-month DPS aggregation treats missing dividend rows as `0.0`.
- **Missing/Invalid Price:** if no valid `price > 0` is found in the allowed lookback window, drop that date.
- **Quality Auditing:** stale price fallback events are logged when applicable.

---

## 2. `ebitda_margin` (Profitability Factor)

| Field | Specification |
|------|--------------|
| Metric Name (code) | `ebitda_margin` |
| Raw Fields | `enterprise_ebitda`, `enterprise_revenue` |
| Origin Source (Input) | Source A financial atomics |
| Target Storage (Output) | PostgreSQL (`systematic_equity.factor_observations`) |
| Frequency | Daily as-of computation using latest eligible financial snapshot |
| History | ≥ 5 years |
| Calculation Logic | `ebitda_margin = enterprise_ebitda / enterprise_revenue` |

### Missing / Error Tolerance & Quality Rules
- **Negative/Zero Revenue:** if `enterprise_revenue <= 0`, drop.
- **Missing Values:** if either numerator or denominator is NULL/NaN/non-numeric, drop.
- **Soft Stale Warning:** if age is in `(270, 365]` days, keep but log stale event.
- **Hard Expiration:** if age is `> 365` days, drop.

---

## 3. `debt_to_equity` (Financial Health Factor)

| Field | Specification |
|------|--------------|
| Metric Name (code) | `debt_to_equity` |
| Raw Fields | `total_debt`, `total_shareholder_equity` |
| Origin Source (Input) | Source A financial atomics |
| Target Storage (Output) | PostgreSQL (`systematic_equity.factor_observations`) |
| Frequency | Daily as-of computation using latest eligible financial snapshot |
| History | ≥ 5 years |
| Calculation Logic | `debt_to_equity = total_debt / total_shareholder_equity` |

### Missing / Error Tolerance & Quality Rules
- **Negative/Zero Equity:** if `total_shareholder_equity <= 0`, drop.
- **Missing Values:** if debt or equity is NULL/NaN/non-numeric, drop.
- **Soft Stale Warning:** if age is in `(270, 365]` days, keep but log stale event.
- **Hard Expiration:** if age is `> 365` days, drop.
- **Interpolation:** none; daily series is stepwise as-of alignment.

---

## 4. `pb_ratio` (Price-to-Book, Valuation Factor)

| Field | Specification |
|------|--------------|
| Metric Name (code) | `pb_ratio` |
| Raw Fields | `adjusted_close_price`, `shares_outstanding`, `total_shareholder_equity` |
| Origin Source (Input) | Source A market + financial atomics |
| Target Storage (Output) | PostgreSQL (`systematic_equity.factor_observations`) |
| Frequency | Daily as-of computation (then sampled by pipeline output frequency) |
| History | ≥ 5 years |
| Calculation Logic | `pb_ratio = (price * shares_outstanding) / total_shareholder_equity` |

### Missing / Error Tolerance & Quality Rules
- **Look-ahead Bias Prevention:** price uses strict backward lookback (max 3 prior trading days).
- **Negative/Zero Inputs:** if equity `<= 0` or shares `<= 0`, drop.
- **Missing/Invalid Price:** if no valid `price > 0` in allowed lookback, drop that date.
- **Financial Staleness:** `(270, 365]` days keep with stale warning; `> 365` days drop.
- **Outlier Control:** monthly cross-sectional cap at p99; fallback cap `100.0` when sample `< 50`.

---

## 5. `sentiment_30d_avg` (News Sentiment, Alternative Risk Factor)

| Field | Specification |
|------|--------------|
| Metric Name (code) | `sentiment_30d_avg` |
| Raw Fields | article `title`, `summary`, `time_published` (plus symbol mapping from ticker hits) |
| Origin Source (Input) | Source B (`NEWS_SENTIMENT`) |
| Target Storage (Output) | MinIO raw JSONL → PostgreSQL (`systematic_equity.factor_observations`) |
| Frequency | Daily |
| History | ≥ 5 years (subject to API availability) |
| Calculation Logic | article sentiment (`title+summary`) → `news_sentiment_daily` by `symbol+date` → calendar zero-fill → rolling `30D` mean |

### Missing / Error Tolerance & Quality Rules
- **Malformed Rows:** invalid symbol/date/value rows are dropped at transform stage.
- **No-News Handling:** missing calendar days are explicitly zero-filled before rolling window computation.
- **Sentiment Capping:** article-level score is clipped to `[-1.0, 1.0]`.
- **Timestamp Policy:** missing `time_published` follows configured strict/non-strict handling, with fallback/drop counters logged.

### Implementation Notes (Current Codebase)
- Source B raw ingestion stores monthly run snapshots and a current-month merged view in MinIO.
- Transform emits atomics `news_sentiment_daily` and `news_article_count_daily`.
- Final rolling signal uses time-window rolling (`rolling('30D')`), not row-count rolling.

---

## 6. `momentum_1m` (Momentum Factor)

| Field | Specification |
|------|--------------|
| Metric Name (code) | `momentum_1m` |
| Raw Fields | `adjusted_close_price` |
| Origin Source (Input) | Source A market atomics |
| Target Storage (Output) | PostgreSQL (`systematic_equity.factor_observations`) |
| Frequency | Daily |
| History | ≥ 5 years |
| Calculation Logic | 1-month momentum from trailing price series (20 trading-day window basis in code path) |

### Missing / Error Tolerance & Quality Rules
- **Price Guards:** rows with missing/non-numeric/`<=0` prices are excluded before calculation.
- **History Requirement:** at least 20 valid observations are required; insufficient history yields no factor row.
- **Numerical Safety:** post-compute NaN/Inf values are filtered before persistence.

---

## 7. `volatility_20d` (Volatility Factor)

| Field | Specification |
|------|--------------|
| Metric Name (code) | `volatility_20d` |
| Raw Fields | `adjusted_close_price` (converted to return series in transform) |
| Origin Source (Input) | Source A market atomics |
| Target Storage (Output) | PostgreSQL (`systematic_equity.factor_observations`) |
| Frequency | Daily |
| History | ≥ 5 years |
| Calculation Logic | trailing 20-day realized volatility from return series |

### Missing / Error Tolerance & Quality Rules
- **Price Guards:** missing/non-numeric/`<=0` prices are removed before return/volatility calculation.
- **History Requirement:** fewer than 20 valid points yields no volatility output row.
- **Numerical Safety:** NaN/Inf outputs are filtered before write.

---

# System-Level Acceptance Criteria (Definition of Done)

The pipeline and infrastructure must pass the following verifiable automated criteria before pull requests can be merged.

### 1. Data Coverage & Integrity Tests (`pytest`)
- **Historical Depth:** Pipeline must successfully backfill and persist ≥ 5 years of data for at least 3 test companies without throwing unhandled exceptions.
- **Missing Data Enforcement:** Unit tests must inject mocked stale data (e.g., Book Value > 12 months old) and explicitly assert that the ETL pipeline drops the observation.
- **Test Coverage Red Line:** The `pytest` suite running over the `transform` and `quality` modules must achieve a minimum of **80% code coverage**.

### 2. Query Capability & Indexing
- **EAV / Long Table Pattern:** The `factor_observations` schema must be designed as a "long table" (e.g., `symbol`, `observation_date`, `factor_name`, `factor_value`) rather than a wide table, satisfying the requirement that *adding a new metric must not require a schema ALTER operation*.
- **Performance:** B-Tree indexes must be applied to `symbol` and `observation_date`. The database must support sub-second query execution times for:
  1. Retrieving all metrics for a single `symbol` over a 5-year period.
  2. Retrieving a specific `factor_name` across all companies for a given calendar year.

### 3. Pipeline Robustness & Fault Tolerance
- **Dynamic Universe:** The pipeline must dynamically query `systematic_equity.company_static` at runtime. Adding or removing a symbol from this table must immediately reflect in the pipeline's execution loop without requiring codebase changes.
- **Idempotency & Uniqueness:** The pipeline must be idempotent. Rerunning the pipeline for the same date range must not duplicate data. PostgreSQL must utilize a composite Unique Constraint (`symbol`, `factor_name`, `observation_date`) combined with an `INSERT ... ON CONFLICT DO UPDATE` (Upsert) strategy.
- **Non-Blocking Execution:** If the API request for `company A` fails (e.g., HTTP 404 or 500), the pipeline must catch the exception, log the error trace to a `pipeline_runs` audit table, and seamlessly continue processing `company B`.
  - Current implementation: primary audit sink is PostgreSQL table `systematic_equity.pipeline_runs`; local JSONL remains as secondary debug mirror.

### 4. Quality Auditability
- **Lineage Tracing:** Every row in the curated PostgreSQL table must include a `run_id` or `updated_at` timestamp linking it back to the specific execution batch that fetched the raw data from MinIO.

