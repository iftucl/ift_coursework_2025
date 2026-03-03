# Data Catalog

This catalog lists implemented datasets, owners, and storage locations.

| Dataset Name | Type | Storage | Description | Owner / Role |
| --- | --- | --- | --- | --- |
| `company_static` | Structured table | PostgreSQL `systematic_equity.company_static` | Dynamic investable universe (symbols and metadata). | Role 5 |
| `company_universe_overrides` | Structured table | PostgreSQL `systematic_equity.company_universe_overrides` | Runtime include/exclude overrides applied on top of base universe selection. | Role 5 |
| `source_a_raw_pricing_fundamentals` | Raw JSON | MinIO `raw/source_a/pricing_fundamentals/...` | Source A raw payloads (Alpha Vantage primary, yfinance fallback). | Role 6 |
| `source_b_raw_news` | Raw JSONL | MinIO `raw/source_b/news/run_date=.../year=.../month=.../symbol=...jsonl` | Source B raw article text payloads (deduplicated by URL or `title+time_published`). | Role 7 |
| `source_b_news_current` | Raw JSONL (merged view) | MinIO `raw/source_b/news_current/year=.../month=.../symbol=...jsonl` | Current month merged single-view per symbol (cross-run merge + dedupe + overwrite). | Role 7 |
| `source_b_news_cursor` | Raw JSON (cursor) | MinIO `raw/source_b/news_cursor/year=.../month=.../symbol=...json` | Incremental cursor metadata (`last_ingested_date`, `is_closed`, fetch window trace fields). | Role 7 |
| `financial_observations` | Structured long table | PostgreSQL `systematic_equity.financial_observations` | Atomic financial metrics with period semantics (`symbol/report_date/metric/value/currency/period_type`). | Role 8 |
| `factor_observations` | Structured long table | PostgreSQL `systematic_equity.factor_observations` | Atomic and final factors in EAV format (`symbol/date/factor/value`). | Role 8 |
| `pipeline_runs` | Structured audit table | PostgreSQL `systematic_equity.pipeline_runs` | Primary run-level audit trail (`running/success/failed`, context, row counts, errors). | Role 8 |
| `dataset_registry` | Structured metadata table | PostgreSQL `systematic_equity.dataset_registry` | Dataset-level metadata registry (owner, location, refresh policy, key definition). | Role 8 |
| `schema_versions` | Structured metadata table | PostgreSQL `systematic_equity.schema_versions` | Versioned schema metadata per dataset (`version_tag`, `schema_json`, current flag). | Role 8 |
| `lineage_edges` | Structured metadata table | PostgreSQL `systematic_equity.lineage_edges` | Dataset lineage edges (`upstream -> downstream`, transformation step). | Role 8 |
| `quality_snapshots` | Structured metadata table | PostgreSQL `systematic_equity.quality_snapshots` | Run-level quality snapshots persisted as JSONB for trend/audit analysis. | Role 8 |
| `news_articles` | Document collection | MongoDB `ift_cw.news_articles` | Search/index serving collection for Source B articles, with canonical `tickers` and `time_published`. | Role 8 |
| `pipeline_runs_jsonl` | JSONL log | Local file `logs/pipeline_runs.jsonl` | Secondary debug mirror of run logs (non-authoritative). | Role 8 |

## Notes

- Source A market atomic factors currently include `adjusted_close_price`, `daily_return`, and `dividend_per_share`.
- Financial atomic metrics (`book_value`, `total_shareholder_equity`, `shares_outstanding`, `total_debt`, `enterprise_ebitda`, `enterprise_revenue`) are persisted to `financial_observations`.
- Source B alternative atomic factors include `news_sentiment_daily` and `news_article_count_daily`.
- Final factor computation is handled by `modules/transform/factors.py` and persisted to `factor_observations` (including recomputed technical factors `momentum_1m` and `volatility_20d`).
- MinIO paths intentionally include `run_date` for traceability and reproducibility.
- Mongo `news_articles` uses canonical fields `time_published` and `tickers`; compatibility aliases `published_at` and `symbols` are also written with the same values.
