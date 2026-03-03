# Architecture Overview

## 1. Objective

Provide a reproducible CW1 pipeline that can start from a fresh environment, ingest multi-source data, enforce quality checks, and persist analytics-ready datasets for Coursework Two.

## 2. System Architecture (Layered View)

```text
                    +------------------------------+
                    |      Runtime Control         |
                    | Main.py / scheduler scripts  |
                    +---------------+--------------+
                                    |
                    +---------------v--------------+
                    |      Input Extraction        |
                    | Source A + Source B modules  |
                    +---------------+--------------+
                                    |
         +--------------------------+--------------------------+
         |                                                     |
+--------v---------+                                   +-------v--------+
|   Raw Data Lake  |                                   | Normalize/QC   |
|      MinIO       |                                   | output/*       |
+--------+---------+                                   +-------+--------+
         |                                                     |
         +--------------------------+--------------------------+
                                    |
                    +---------------v--------------+
                    |      Curated Storage         |
                    | PostgreSQL (factors/fin)     |
                    +---------------+--------------+
                                    |
                    +---------------v--------------+
                    |  Metadata + Audit + Optional |
                    |  Mongo Search Index          |
                    +------------------------------+
```

## 3. End-to-End Data Flow

1. Resolve runtime parameters with precedence:
   `CLI > .env > config/conf.yaml > defaults`.
2. Read dynamic universe from PostgreSQL `systematic_equity.company_static`.
3. Run extraction:
   - Source A: market and fundamentals
   - Source B: news and sentiment
4. Archive raw payloads to MinIO for replay and auditability.
5. Normalize atomic records and run quality checks.
6. Upsert curated data to PostgreSQL:
   - `factor_observations`
   - `financial_observations`
   - `pipeline_runs`
7. Compute final factors (`modules.transform.factors`) and write back to curated factors.
8. Index Source B records into MongoDB `ift_cw.news_articles` by default in scheduler/orchestrator scripts; disable explicitly with `--no-index-mongo`.
   - `Main.py` itself does not directly index MongoDB.
   - Mongo indexing is intentionally separated as a post-run serving step.
9. Persist metadata governance state:
   - `dataset_registry`
   - `schema_versions`
   - `lineage_edges`
   - `quality_snapshots`

## 4. Storage Topology

### MinIO (raw data lake)

- `raw/source_a/pricing_fundamentals/run_date={YYYY-MM-DD}/year={YYYY}/symbol={SYMBOL}.json`
- `raw/source_b/news/run_date={YYYY-MM-DD}/year={YYYY}/month={MM}/symbol={SYMBOL}.jsonl`

### PostgreSQL (curated, audit, metadata)

- Curated data:
  - `systematic_equity.factor_observations`
  - `systematic_equity.financial_observations`
- Run audit:
  - `systematic_equity.pipeline_runs`
- Metadata management:
  - `systematic_equity.dataset_registry`
  - `systematic_equity.schema_versions`
  - `systematic_equity.lineage_edges`
  - `systematic_equity.quality_snapshots`

### MongoDB (serving index; enabled by default in scheduler/orchestrator scripts)

- `ift_cw.news_articles`

## 5. Reliability and Idempotency

| Control point | Mechanism |
| --- | --- |
| Factor deduplication | Unique key `(symbol, observation_date, factor_name)` |
| Financial deduplication | Unique key `(symbol, report_date, metric_name)` |
| Rerun safety | Upsert-based loaders in output layer |
| Run traceability | `pipeline_runs` status lifecycle (`running/success/failed`) |

## 6. Scheduling and Frequency Flexibility

- Main runtime supports `--run-date` and `--frequency`.
- Scheduler wrapper supports frequency selection:
  `--only daily,weekly,monthly,quarterly`.
- Auto job script is intentionally fixed to daily for production default behavior.

## 7. Quality and Security Gates

| Area | Tooling / script |
| --- | --- |
| Data consistency | `scripts/validate_pipeline_data.py` |
| Automated tests | `pytest` with coverage threshold (`>=80%`) |
| Static security checks | `bandit` |
| Dependency vulnerability checks | `safety` |

## 8. Acceptance Checklist (From Zero)

1. Start containers (PostgreSQL, MongoDB, MinIO).
2. Run schema bootstrap (`scripts/init_db.py`).
3. Execute pipeline run (`Main.py` or small-sample wrapper).
4. Validate loaded data (`validate_pipeline_data.py`).
5. Confirm records exist in all required stores.
