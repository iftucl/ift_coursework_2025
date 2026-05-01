# Data Catalog

| Dataset | Type | Storage | Description |
| --- | --- | --- | --- |
| `company_static` | structured table | PostgreSQL `systematic_equity.company_static` | base company universe seeded from `000.Database/SQL/Equity.db` |
| `company_universe_overrides` | structured table | PostgreSQL `systematic_equity.company_universe_overrides` | runtime include/exclude controls |
| `source_a_raw_pricing_fundamentals` | raw JSON | MinIO `raw/source_a/{market,financial}/...` | Source A merged raw market and financial payload archive with metric-level provider provenance in the financial layer |
| `source_b_raw_news` | raw JSONL | MinIO `raw/source_b/news/run_date=.../year=.../month=.../symbol=...jsonl` | Source B monthly provider snapshot |
| `source_b_news_current` | raw JSONL | MinIO `raw/source_b/news_current/year=.../month=.../symbol=...jsonl` | merged current-month Source B view |
| `source_b_news_cursor` | raw JSON | MinIO `raw/source_b/news_cursor/year=.../month=.../symbol=...json` | per-symbol per-month incremental cursor |
| `factor_observations` | structured long table | PostgreSQL `systematic_equity.factor_observations` | atomic and final non-financial factors |
| `financial_observations` | structured long table | PostgreSQL `systematic_equity.financial_observations` | filing-period financial atomics |
| `pipeline_runs` | structured audit table | PostgreSQL `systematic_equity.pipeline_runs` | run status, row counts, error notes |
| `pipeline_stage_events` | structured audit table | PostgreSQL `systematic_equity.pipeline_stage_events` | append-only stage telemetry per run |
| `dataset_refresh_events` | structured audit table | PostgreSQL `systematic_equity.dataset_refresh_events` | append-only dataset refresh evidence |
| `dataset_registry` | structured metadata table | PostgreSQL `systematic_equity.dataset_registry` | dataset-level metadata |
| `schema_versions` | structured metadata table | PostgreSQL `systematic_equity.schema_versions` | schema registry |
| `lineage_edges` | structured metadata table | PostgreSQL `systematic_equity.lineage_edges` | lineage graph edges |
| `quality_snapshots` | structured metadata table | PostgreSQL `systematic_equity.quality_snapshots` | quality evidence snapshots |
| `news_articles` | document collection | MongoDB `ift_cw.news_articles` | rebuildable Source B search layer |
| `pipeline_runs_jsonl` | JSONL log | `logs/pipeline_runs.jsonl` | local debug mirror only |

## Notes

- `Source A` raw storage is a canonical merged replay layer. Market data live under `raw/source_a/market/...`; financial data live under `raw/source_a/financial/...`. Financial payloads keep both the winning value and per-metric provider provenance, including `provider_values_by_metric`, `value_source_by_metric`, and `publish_date_source_by_metric`.
- `EDGAR` is part of `Source A` financial enrichment, not a separate top-level source. The current raw layer stores the merged result rather than a provider-native `EDGAR` raw archive.
- `financial_observations` uses `report_date` as the filing-period key and `publish_date` as the primary PIT availability field. `factor_observations` remains keyed by `observation_date`.
- `CW1 as_of` and `CW2 as_of_date` are intentionally different. `as_of` in CW1 means extraction/audit date; `as_of_date` in CW2 means snapshot/decision date.
- Source B is fully based on Alpha Vantage (historical) and Finnhub (incremental).
- Redis is not a business-data catalog store; it is a shared operational state store for resilience controls and dedupe.
- Sphinx HTML output is published to `docs/sphinx/build/html`.
