# API Reference

This page maps the code API to the actual pipeline runtime architecture.
Use it to understand call flow first, then inspect details in **Module Index** and **View Source**.

## 1. Pipeline Call Graph (High Level)

```text
main()
  -> resolve_runtime(...)
  -> run_pipeline_stage(...)
       -> input.extract_source_a(...)
       -> input.extract_source_b(...)
       -> output.normalize_*(...)
       -> output.run_quality_checks(...)
       -> output.load_*(...)
       -> transform.build_and_load_final_factors(...)
       -> output.metadata.write_quality_snapshot(...)
  -> finalize_audit_and_runlog(...)
```

## 2. Layer Responsibilities

| Layer | Module path | Purpose |
| --- | --- | --- |
| Main pipeline | `Main.py` | Runtime orchestration and stage execution |
| DB | `modules/db/*` | Database connectivity and universe access |
| Input | `modules/input/*` | Source extraction and raw ingestion |
| Output | `modules/output/*` | Normalize, quality, load, audit, metadata |
| Transform | `modules/transform/factors.py` | Final factor computation and load-back |
| Utils | `modules/utils/*` | CLI parsing and env loading |

## 3. Main Pipeline API (`Main.py`)

### Core runtime types

| Type | Responsibility |
| --- | --- |
| `RunLog` | Run-level JSONL mirror payload |
| `RunContext` | Resolved runtime config and execution context |
| `PipelineState` | Mutable state across pipeline stages |

### Main entrypoints

| Function | Responsibility |
| --- | --- |
| `main()` | Top-level pipeline entrypoint |
| `resolve_runtime(...)` | Resolve CLI/env/config into validated context |
| `run_pipeline_stage(...)` | Execute extract -> normalize -> quality -> load -> transform |
| `finalize_audit_and_runlog(...)` | Persist audits and return process exit code |

## 4. DB Access API (`modules/db`)

### Database and universe functions

| Function | Responsibility |
| --- | --- |
| `db_connection.get_db_engine()` | SQLAlchemy engine from `POSTGRES_*` |
| `db_connection.get_db_connection()` | Raw DB connection for compatibility |
| `universe.get_company_universe(...)` | Dynamic universe retrieval with override support |
| `universe.get_company_count()` | Universe cardinality query |

## 5. Input Extraction API (`modules/input`)

### Source A and Source B

| Function | Responsibility |
| --- | --- |
| `extract_source_a.extract_source_a(...)` | Market + fundamentals extraction and raw archive |
| `extract_source_a.load_config(...)` | Source A config loader |
| `extract_source_b.ingest_source_b_raw(...)` | Monthly raw news ingestion to MinIO |
| `extract_source_b.transform_source_b_features(...)` | Daily sentiment/count factor conversion |
| `extract_source_b.extract_source_b(...)` | Source B end-to-end wrapper |
| `extract_source_b.compute_sentiment_scores(...)` | Sentiment score helper |
| `symbol_filter.symbol_allowed(...)` | Symbol-level policy check |
| `symbol_filter.filter_symbols(...)` | Filter + dedupe symbol list |

## 6. Output Processing API (`modules/output`)

### Normalize, quality, load, metadata

| Function | Responsibility |
| --- | --- |
| `normalize.normalize_records(...)` | Normalize atomic factor records |
| `normalize.normalize_financial_records(...)` | Normalize financial atomic records |
| `quality.run_quality_checks(...)` | Quality report generation |
| `load.load_curated(...)` | Curated factor upsert loader |
| `load.load_financial_observations(...)` | Financial table upsert loader |
| `audit.write_pipeline_run_start(...)` | Run-start audit persistence |
| `audit.write_pipeline_run_finish(...)` | Run-finish audit persistence |
| `metadata.bootstrap_metadata_catalog(...)` | Dataset/schema/lineage bootstrap |
| `metadata.write_quality_snapshot(...)` | Run-level quality snapshot persistence |

## 7. Transform API (`modules/transform`)

### Final factor computation

| Function | Responsibility |
| --- | --- |
| `factors.compute_final_factor_records(...)` | Compute final factor rows from atomic inputs |
| `factors.build_and_load_final_factors(...)` | Load atomics, compute finals, upsert results |

## 8. Utility API (`modules/utils`)

### CLI and environment helpers

| Function | Responsibility |
| --- | --- |
| `args_parser.build_parser(...)` | CLI parser builder for main pipeline |
| `env.load_dotenv_if_exists(...)` | `.env` loader with safe non-override behavior |

## 9. How to inspect full API details

After building docs, use:

1. **Module Index** (`py-modindex.html`) for module-level symbol navigation.
2. **General Index** (`genindex.html`) for function and class lookup.
3. **View Source** links on API pages for exact implementation details.
