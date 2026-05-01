# Data Dictionary

## `systematic_equity.factor_observations`

Curated long-table store for market atomics, Source B atomics, and final factors.

| Column | Meaning |
| --- | --- |
| `symbol` | equity ticker |
| `observation_date` | business date of the factor |
| `factor_name` | metric identifier |
| `factor_value` | numeric factor value |
| `source` | provider or transform label |
| `metric_frequency` | `daily`, `weekly`, `monthly`, `quarterly`, `annual`, or `unknown` |
| `source_report_date` | provider reference date when applicable |
| `publish_date` | Point-in-time availability date. For daily market and macro factors this is naturally the same-day `observation_date`; for lagged factors it is stored explicitly and must satisfy `publish_date <= rebalance_date`. |
| `updated_at` | write timestamp |

### Source A atomics (yfinance)

| factor_name | Description |
| --- | --- |
| `adjusted_close_price` | Split/dividend-adjusted closing price |
| `open_price` | Daily opening price |
| `high_price` | Daily high price |
| `low_price` | Daily low price |
| `daily_return` | Log return: ln(close_t / close_{t-1}) |
| `dividend_per_share` | Cash dividend per share on ex-date |
| `daily_volume` | Trading volume (shares) |

### Source B atomics (AV + Finnhub + L-M sentiment)

| factor_name | Description |
| --- | --- |
| `news_sentiment_daily` | Raw daily L-M sentiment score per article |
| `news_article_count_daily` | Raw daily article count per symbol |

### Sentiment transform factors

| factor_name | Description |
| --- | --- |
| `sentiment_7d_avg` | 7-day rolling average sentiment score |
| `sentiment_30d_avg` | 30-day rolling average sentiment score |
| `sentiment_dispersion_7d` | 7-day rolling std dev of sentiment (disagreement signal) |
| `article_count_7d` | Article count in trailing 7-day window |
| `article_count_30d` | Article count in trailing 30-day window |
| `sentiment_surprise` | sentiment_7d_avg − sentiment_30d_avg (momentum inflection) |

### Market transform factors

| factor_name | Description |
| --- | --- |
| `momentum_3m` | 63-day cumulative return |
| `momentum_6m` | 126-day cumulative return |
| `momentum_12m` | Legacy storage name for 12-1M momentum: 252-day return, skipping the latest 21 trading days. CW2 maps this field to `momentum_12_1m`. |
| `volatility_60d` | 60-day daily return std dev |
| `realized_vol_60d` | 60-day annualised realized volatility |
| `garch_vol_60d` | 60-day GARCH(1,1) conditional volatility |
| `beta_1y` | Cov(stock, benchmark) / Var(benchmark), 252-day rolling |
| `liquidity_20d` | 20-day avg daily dollar volume |
| `log_market_cap` | ln(price × shares_outstanding) |
| `ep_ratio` | EPS / Price (earnings-to-price) |
| `ebitda_to_ev` | EBITDA / Enterprise Value |
| `payout_ratio` | DPS_TTM / EPS |
| `dividend_stability` | Multi-year dividend-policy stability score from trailing TTM DPS history |

### Macro indicators (symbol = `_MACRO`)

| factor_name | Description |
| --- | --- |
| `vix_close` | CBOE Volatility Index daily close |
| `us_treasury_10y` | US 10-Year Treasury Yield |
| `us_treasury_5y` | US 5-Year Treasury Yield |
| `us_treasury_3m` | US 3-Month Treasury Bill Rate |

## `systematic_equity.financial_observations`

Curated long-table store for filing-period metrics.

| Column | Meaning |
| --- | --- |
| `symbol` | equity ticker |
| `report_date` | filing period end date |
| `metric_name` | financial metric identifier |
| `metric_value` | numeric value |
| `currency` | source currency |
| `period_type` | `annual`, `quarterly`, `ttm`, `snapshot`, or `unknown` |
| `metric_definition` | semantic definition tag |
| `source` | winning provider for the final stored value; downstream same-source pairing logic reads this field |
| `value_source` | explicit numeric-value source, currently aligned with `source` but stored separately for provenance clarity |
| `as_of` | extraction/audit date used when the pipeline fetched or replayed this record; not the decision date |
| `publish_date` | point-in-time availability date for the filing-period metric; this is the PIT gate used by downstream financial reads |
| `publish_date_source` | provenance for the timing field such as `edgar_xbrl`, `provider_date`, or `fallback_45d` |
| `updated_at` | write timestamp |

Notes:
- `financial_observations` is strict-PIT by design: `report_date` is the fiscal period, while `publish_date` is the availability date.
- `CW1 as_of` should be read as extraction/audit lineage. It is not the same concept as `CW2 as_of_date`.

Cross-layer time-key note:
- `CW1 as_of` = extraction/audit date on upstream curated financial rows
- `CW2 as_of_date` = snapshot/decision date for feature, target, recommendation, and backtest layers
- `CW2 signal_as_of_date` = latest factor/event signal date used by update-decision monitoring
- These fields are intentionally different and should not be joined as if they were the same clock.

## `systematic_equity.pipeline_runs`

Run-level audit table.

| Column | Meaning |
| --- | --- |
| `run_id` | unique batch identifier |
| `run_date` | business date used for the run |
| `status` | `running`, `success`, or `failed` |
| `frequency` | requested output sampling frequency |
| `backfill_years` | history depth used |
| `company_limit` | optional universe cap |
| `enabled_extractors` | extractor list for the run |
| `rows_written` | total curated rows written |
| `error_message` | summary error field |
| `notes` | provider or stage notes |

## `systematic_equity.pipeline_stage_events`

Append-only stage telemetry table.

| Column | Meaning |
| --- | --- |
| `run_id` | parent pipeline batch identifier |
| `stage_name` | normalized stage/task name such as `atomic_persist` or `mongo_index` |
| `status` | `running`, `ok`, `warning`, `failed`, or `skipped` |
| `rows_in` | optional input unit count |
| `rows_out` | optional output row count |
| `elapsed_ms` | stage elapsed time in milliseconds |
| `details_json` | structured diagnostic payload |
| `event_at` | append timestamp |

## `systematic_equity.dataset_refresh_events`

Append-only dataset refresh evidence table.

| Column | Meaning |
| --- | --- |
| `run_id` | parent pipeline batch identifier |
| `run_date` | business date used for the run |
| `dataset_name` | refreshed dataset registered in `dataset_registry` |
| `stage_name` | producing stage such as `atomic_persist`, `transform_final`, `mongo_index` |
| `status` | `ok`, `warning`, `failed`, or `skipped` |
| `rows_written` | rows inserted or updated for that dataset-stage event |
| `details_json` | structured write stats / diagnostics |
| `event_at` | append timestamp |

## `systematic_equity.benchmark_prices`

Daily closing prices for benchmark indices. Separate from factor_observations to maintain clear semantic distinction between benchmark reference data and alpha factors.

| Column | Meaning |
| --- | --- |
| `ticker` | Yahoo Finance benchmark ticker (e.g. `SPY`) |
| `price_date` | Trading date |
| `close_price` | Daily closing price |
| `daily_return` | Log return: ln(close_t / close_{t-1}). NULL for first row |
| `source` | Data provider (default: `yfinance`) |
| `updated_at` | Write timestamp |

## Source A Raw JSON Schema

Current MinIO Source A raw objects are normalized around these fields:

| Field | Meaning |
| --- | --- |
| `symbol` | ticker symbol |
| `run_date` | business date used for the extraction |
| `as_of_date` | same-day replay anchor for the raw payload |
| `rows` | normalized history row count |
| `history[].observation_date` | canonical trading date |
| `history[].Open/High/Low/Close` | normalized OHLC values when available |
| `history[].Dividends` | normalized dividend-per-share value |
| `history[].Volume` | normalized daily volume |
| `total_debt` | top-level convenience snapshot when available |
| `fundamentals` | extracted fundamental snapshot block |
| `fundamentals.publish_date_by_metric` | per-metric availability dates for the merged financial payload |
| `fundamentals.publish_date_source_by_metric` | provenance for each per-metric publish date |
| `fundamentals.value_source_by_metric` | winning provider for each stored financial metric |
| `fundamentals.provider_values_by_metric` | per-metric provider candidate values retained before the winning merged value is chosen |
| `source_used` | provider selected by routing logic |
| `normalized_schema_version` | normalized raw-object schema version tag |
| `provider_payload_version` | provider payload contract/version tag when known |
| `schema_validation_status` | `valid` or `warning` after normalization checks |
| `schema_validation_errors` | list of non-fatal parsing/shape issues |

Raw-layer note:
- `raw/source_a/market/...` and `raw/source_a/financial/...` are canonical merged replay objects, not separate provider-native archives.
- Market data follow `yfinance` primary, `Alpha Vantage` fallback.
- Financial values are merged with `yfinance` scaffold, `Alpha Vantage` gap fill, and `EDGAR` authoritative on mapped overlapping core metrics.
- `EDGAR` also remains the preferred `publish_date` source where filing dates are available.

## Source B Raw JSONL Schema

Current MinIO Source B objects are normalized around these fields:

| Field | Meaning |
| --- | --- |
| `article_id` | provider article identifier when available |
| `symbol` / `ticker` | primary ticker namespace for the record |
| `time_published` | compact publish timestamp |
| `title` / `headline` | article headline |
| `summary` | article summary text |
| `url` | canonical article URL |
| `source` | publisher/source name |
| `data_source` | provider path, typically `alpha_vantage` or `finnhub` |
| `publish_date` | canonical provider publish date in `YYYY-MM-DD` form |
| `time_precision` | `timestamp`, `date`, or `missing` depending on source granularity |
| `normalized_schema_version` | normalized raw-object schema version tag |
| `provider_payload_version` | provider payload contract/version tag when known |
| `schema_validation_status` | `valid` or `warning` after normalization checks |
| `schema_validation_errors` | list of non-fatal parsing/shape issues seen during normalization |
| `topics` | provider topic list |
| `ticker_hits` | provider ticker association payload |

## MongoDB `ift_cw.news_articles`

Serving/search collection rebuilt from MinIO Source B data.

| Field | Meaning |
| --- | --- |
| `_id` | stable article identifier |
| `title` | article title |
| `summary` | article summary |
| `url` | canonical URL |
| `time_published` | canonical publish time |
| `symbols` | mapped ticker list |
| `source` | provider/source label |
| `first_seen_run_date` | first indexed run date |
| `last_seen_run_date` | latest indexed run date |
| `minio_object_keys` | raw lineage pointers |
