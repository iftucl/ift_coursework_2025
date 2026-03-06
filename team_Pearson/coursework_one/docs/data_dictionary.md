# Data Dictionary

This document reflects the current implemented schema in `team_Pearson/coursework_one/sql/init.sql` and the current pipeline behavior.

## 1. Table: `systematic_equity.company_static`

Primary upstream universe table used by the pipeline (`modules/db/universe.py`).

| Column Name | Type | Description | Notes |
| --- | --- | --- | --- |
| `symbol` | TEXT / VARCHAR | Company symbol code | Universe key used by extractors |
| `company_name` | TEXT | Company name | Optional in pipeline logic |
| `country` | TEXT | Country code/name | Used by country allowlist filter |
| `sector` | TEXT | Sector name | Optional metadata |

Universe read behavior in current code:
- Primary read target: `systematic_equity.company_static`
- Fallback read target: `systematic_equity.equity_static` (if primary query fails)
- Final universe can be adjusted by active rows in `systematic_equity.company_universe_overrides`

## 1.1 Table: `systematic_equity.company_universe_overrides`

Optional runtime override table for include/exclude controls, managed by `scripts/manage_universe_overrides.py`.

| Column Name | Type | Description | Notes |
| --- | --- | --- | --- |
| `symbol` | VARCHAR(50) | Company symbol code | Primary key |
| `action` | VARCHAR(20) | Override action | Check: `include` / `exclude` |
| `is_active` | BOOLEAN | Whether override is active | Default `TRUE` |
| `reason` | TEXT | Operator note | Nullable |
| `updated_at` | TIMESTAMPTZ | Last update time | Default `CURRENT_TIMESTAMP` |

Supporting index:
- `idx_company_universe_overrides_action_active`

## 2. Table: `systematic_equity.factor_observations`

Curated long-table factor store.

| Column Name | Type | Description | Notes |
| --- | --- | --- | --- |
| `id` | SERIAL | Surrogate primary key | Auto-increment |
| `symbol` | VARCHAR(50) | Company symbol code | Required |
| `observation_date` | DATE | Factor date | Required |
| `factor_name` | VARCHAR(50) | Factor identifier | Required |
| `factor_value` | NUMERIC(18,6) | Factor numeric value | Nullable |
| `source` | VARCHAR(50) | Data source or transform stage | e.g. `alpha_vantage`, `yfinance`, `extractor_b`, `factor_transform` |
| `metric_frequency` | VARCHAR(20) | Frequency tag | Check constraint: `daily/weekly/monthly/quarterly/annual/unknown` |
| `source_report_date` | DATE | Source report/reference date | Nullable |
| `updated_at` | TIMESTAMP | Row update timestamp | Default `CURRENT_TIMESTAMP` |

Constraints and indexes:
- Unique key: `UNIQUE(symbol, observation_date, factor_name)` (`uniq_observation`)
- Index: `idx_factor_obs_symbol` on `symbol`
- Index: `idx_factor_obs_observation_date` on `observation_date`
- Index: `idx_factor_obs_symbol_factor_date` on `(symbol, factor_name, observation_date)`
- Index: `idx_factor_obs_factor_date` on `(factor_name, observation_date)`

Current atomic factors (input/ingest stage):
- `adjusted_close_price`
- `daily_return` (log return: `ln(price_t / price_t-1)`)
- `dividend_per_share`
- `news_sentiment_daily`
- `news_article_count_daily`

Current final factors (transform stage):
- `momentum_1m`
- `volatility_20d`
- `dividend_yield`
- `pb_ratio`
- `debt_to_equity`
- `ebitda_margin`
- `sentiment_30d_avg`
- `article_count_30d`

## 3. Table: `systematic_equity.financial_observations`

Atomic fundamentals store with financial-report semantics.

| Column Name | Type | Description | Notes |
| --- | --- | --- | --- |
| `id` | SERIAL | Surrogate primary key | Auto-increment |
| `symbol` | VARCHAR(50) | Company symbol code | Required |
| `report_date` | DATE | Financial report period-end | Required |
| `metric_name` | VARCHAR(100) | Financial metric identifier | Required |
| `metric_value` | NUMERIC(18,6) | Metric numeric value | Nullable |
| `currency` | VARCHAR(16) | Currency code | Nullable; often `USD`/`UNKNOWN` |
| `period_type` | VARCHAR(20) | Financial period type | Check constraint: `annual/quarterly/ttm/snapshot/unknown` |
| `metric_definition` | VARCHAR(50) | Value definition/semantic tag | Check: `provider_reported/normalized/estimated/unknown` |
| `source` | VARCHAR(50) | Data source | e.g. `alpha_vantage`, `yfinance` |
| `as_of` | DATE | Observation/snapshot date | Nullable |
| `updated_at` | TIMESTAMP | Row update timestamp | Default `CURRENT_TIMESTAMP` |

Constraints and indexes:
- Unique key: `UNIQUE(symbol, report_date, metric_name)` (`uniq_financial_observation`)
- Index: `idx_financial_obs_symbol` on `symbol`
- Index: `idx_financial_obs_report_date` on `report_date`

Current financial atomic metrics:
- `total_debt`
- `book_value`
- `total_shareholder_equity`
- `shares_outstanding`
- `enterprise_ebitda`
- `enterprise_revenue`

## 4. Table: `systematic_equity.pipeline_runs`

Primary pipeline audit table (source of truth for run-level traceability).

| Column Name | Type | Description | Notes |
| --- | --- | --- | --- |
| `run_id` | VARCHAR(64) | Unique pipeline run ID | Primary key |
| `run_date` | DATE | Business run date from CLI | Required |
| `started_at` | TIMESTAMPTZ | UTC start time | Required |
| `finished_at` | TIMESTAMPTZ | UTC finish time | Nullable until finished |
| `status` | VARCHAR(20) | Run status | Check: `running/success/failed` |
| `frequency` | VARCHAR(20) | CLI frequency | Nullable |
| `backfill_years` | INT | Backfill depth | Nullable |
| `company_limit` | INT | Universe limit | Nullable |
| `enabled_extractors` | TEXT | Active extractor list | e.g. `source_a,source_b` |
| `rows_written` | INT | Number of rows written | Default `0` |
| `error_message` | TEXT | Error summary | Nullable |
| `error_traceback` | TEXT | Error traceback | Nullable |
| `notes` | TEXT | Scheduling/provider notes | Nullable |
| `created_at` | TIMESTAMPTZ | Insert timestamp | Default `CURRENT_TIMESTAMP` |
| `updated_at` | TIMESTAMPTZ | Update timestamp | Default `CURRENT_TIMESTAMP` |

Supporting index:
- `idx_pipeline_runs_run_date`
- `idx_pipeline_runs_status`

## 5. File-Based Audit Mirror

Secondary debug mirror:
- `logs/pipeline_runs.jsonl`

This mirror is for local troubleshooting only; PostgreSQL `systematic_equity.pipeline_runs` is the authoritative audit source.

## 6. Mongo Collection: `ift_cw.news_articles`

News search/index document model built by `scripts/index_news_to_mongo.py`.

Default write path:
- `Main.py` triggers this Mongo indexing stage by default after a successful core run.
- Stage can be disabled with `--no-index-mongo`.
- Stage is best-effort: indexing failures are warning-only and do not invalidate SQL core load success.

| Field Name | Type | Description | Notes |
| --- | --- | --- | --- |
| `_id` | STRING | Global article identifier | URL hash primary; fallback hash of source+time+title |
| `title` | STRING | Article title | Text-indexed |
| `summary` | STRING | Article summary | Text-indexed |
| `url` | STRING | Article URL | Sparse unique index |
| `time_published` | DATETIME | Canonical publish time | Indexed |
| `published_at` | DATETIME | Compatibility alias of `time_published` | Same value as canonical field |
| `symbols` | ARRAY\<STRING\> | Canonical mapped symbols for this article | Array because one article can map to multiple symbols |
| `tickers` | ARRAY\<STRING\> | Compatibility alias of `symbols` | Same array values |
| `source` | STRING | News provider/source | Optional |
| `first_seen_run_date` | STRING | First run date this article was indexed | Traceability |
| `last_seen_run_date` | STRING | Latest run date this article was seen | Traceability |
| `minio_object_keys` | ARRAY\<STRING\> | Raw object lineage pointers | Traceability |

Field naming rule:
- Mongo news docs intentionally use array fields `symbols`/`tickers` instead of singular `symbol`.
- Canonical query/index field is `symbols`; `tickers` is retained for backward compatibility.
- Reason: one news article may reference multiple companies; singular `symbol` would lose this cardinality.

Current Mongo index set (from `scripts/index_news_to_mongo.py`):
- text index: `title + summary`
- time index: `time_published`
- symbol index: `symbols`
- symbol+time index: `(symbols, time_published DESC)`
- sparse unique index: `url`
- run tracking indexes: `last_seen_run_date`, `(last_seen_run_date, time_published DESC)`
