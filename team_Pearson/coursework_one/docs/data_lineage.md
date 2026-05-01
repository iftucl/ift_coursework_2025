# Data Lineage

## End-to-End Flow

1. Universe selection
- read `systematic_equity.company_static`
- apply `company_universe_overrides`

Benchmark reference flow
- fetch benchmark price history for `market_factors.benchmark_ticker`
- store benchmark series in `systematic_equity.benchmark_prices`
- use benchmark returns in beta and downstream evaluation metrics

2. Source A ingestion
- fetch market history with `yfinance` primary and `Alpha Vantage` fallback
- build merged Source A financial payloads with `yfinance` scaffold and `Alpha Vantage` gap fill
- enrich overlapping mapped financial metrics with `EDGAR XBRL`, using `EDGAR` as the preferred filing-date source and authoritative provider on mapped overlapping core financial atomics
- archive merged market and financial payloads to MinIO
- normalize to atomic rows

3. Source B ingestion
- fetch historical news from `Alpha Vantage` (before cutoff date)
- fetch incremental news from `Finnhub` (after cutoff date)
- merge and deduplicate provider payloads
- store monthly raw snapshots, current-month merged JSONL, and cursor state in MinIO
- score article text with the Loughran-McDonald lexicon
- emit `news_sentiment_daily` and `news_article_count_daily`

4. Curated load
- normalize records
- run quality checks
- upsert curated atomics into PostgreSQL

5. Final-factor build
- read atomic data back from PostgreSQL
- compute composite and rolling factors
- upsert final factor rows into `factor_observations`

6. Audit and serving
- write run audit to `pipeline_runs`
- write quality and metadata snapshots
- best-effort index Source B articles into MongoDB

7. Scheduling and docs
- Airflow DAG `cw1_pipeline_and_docs` runs the scheduler wrapper
- Airflow then validates curated data
- Airflow then builds Sphinx HTML

## Factor-Level Lineage

| Output | Upstream atomics |
| --- | --- |
| `dividend_yield` | `dividend_per_share`, `adjusted_close_price` |
| `pb_ratio` | `adjusted_close_price`, `shares_outstanding`, `total_shareholder_equity` |
| `debt_to_equity` | `total_debt`, `total_shareholder_equity` |
| `ebitda_margin` | `enterprise_ebitda`, `enterprise_revenue` |
| `momentum_1m` | `adjusted_close_price` |
| `volatility_20d` | `adjusted_close_price`, `daily_return` |
| `sentiment_30d_avg` | `news_sentiment_daily` |
| `article_count_30d` | `news_article_count_daily` |

## Storage Lineage

- MinIO is the raw replay layer
- `raw/source_a/financial/...` is a merged canonical replay object with per-metric provider provenance; it is not a provider-native `EDGAR` raw archive
- PostgreSQL is the curated source of truth
- MongoDB is a derivable serving layer
- Redis stores shared runtime state only and is not part of the analytical truth path

## Time-Key Notes

- `CW1 as_of` means extraction/audit date on provider-facing records such as `financial_observations`
- `CW2 as_of_date` means snapshot/decision date for feature, portfolio, and backtest layers
- `CW2 signal_as_of_date` means the latest factor/event signal date used by the daily update-decision layer; this may equal `run_date`, but on non-trading days it can fall back to the latest eligible trading-day signal date
- The names are intentionally different by layer even though they look similar; `as_of` should not be read as the same business concept as `as_of_date`
- Cross-layer SQL checks should therefore join on the appropriate business clock explicitly, rather than matching similarly named fields by default
