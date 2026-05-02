# Platform Compliance Mapping

## Scope

This platform should be evaluated as an **end-to-end production-style investment
research and portfolio operations stack**, not as a single ETL script. The
relevant scope spans:

- `CW1` ingestion, resilience, normalization, and storage
- `CW2` factor engineering, composite alpha, risk overlay, portfolio
  construction, recommendation, backtest, analysis, and reporting
- Airflow orchestration
- Sphinx documentation automation
- Kafka event fan-out for incremental risk and operational events

## Requirement Mapping

| Domain | Status | Evidence |
| --- | --- | --- |
| Script-driven operation | Met | `coursework_one/Main.py`, `coursework_two/Main.py`, scheduler-safe wrappers in `coursework_two/scripts/` |
| Structured database-backed processing | Met | PostgreSQL schemas in `sql/init.sql`, `cw2_feature_schema.sql`, `cw2_backtest_schema.sql`, `cw2_analysis_schema.sql`, `cw2_recommendation_schema.sql`, `cw2_reporting_schema.sql` |
| Raw archive and replay | Met | MinIO paths in `modules/input/extract_source_b.py`, raw replay tooling in `scripts/import_raw_news_to_minio.py` |
| Alternative data ingestion | Met | `modules/input/extract_source_b.py`, `modules/extract/finnhub_news.py` |
| PIT-safe factor construction | Met | `modules/transform/factors.py`, `coursework_two/modules/feature/factor_engine.py` |
| Portfolio construction with constraints | Met | `coursework_two/modules/portfolio/construction.py` |
| Risk overlay and event-driven actions | Met | `coursework_two/modules/backtest/intraday.py`, `coursework_two/modules/risk/actions.py` |
| Recommendation workflow with approval states | Met | `coursework_two/modules/recommendation/publisher.py` |
| Backtest with execution realism | Met | `coursework_two/modules/backtest/execution.py`, `coursework_two/modules/backtest/engine.py` |
| Analysis and reporting artifacts | Met | `coursework_two/modules/analysis/__init__.py`, `coursework_two/modules/reporting/report.py` |
| Shared resilience controls | Met | `modules/utils/resilience.py`, Redis-backed rate limiting and circuit breaking |
| Automated orchestration | Met | Airflow DAGs in `airflow/dags/` |
| Automated documentation build | Met | `scripts/build_sphinx_docs.py`, DAG task `build_sphinx_docs` |
| Event bus for incremental fan-out | Met | `modules/utils/kafka.py`, Kafka config in both CW1 and CW2 configs |
| Audit, readiness, and quality gates | Met | `coursework_two/modules/ops/audit.py`, `modules/output/quality.py` |

## Storage Compliance

The platform uses **role-specific persistence**, not a single storage engine for
every artifact:

- `PostgreSQL` stores structured, queryable business truth
- `MinIO` stores replayable raw and intermediate archive objects
- `MongoDB` stores the searchable news-serving layer
- `Redis` stores runtime resilience and deduplication state
- `Kafka` carries incremental event fan-out and operational signals

This design is consistent with production research platforms where raw,
curated, searchable, operational, and event-stream concerns are separated.

## Operational Compliance

The platform is operationally compliant with a production-style workflow because
it supports:

- deterministic CLI execution
- scheduler execution via Airflow
- auditable database materialization
- run-level metadata and manifests
- recommendation approval states
- report artifact registration
- readiness and storage health checks

## Current Boundary

The current platform should be described as **production-style and
institutional-grade for coursework scope**, with the following intentional
boundary:

- historical truth remains database- and archive-backed
- Kafka augments incremental eventing but does not replace SQL-backed backtest
  and analysis
- free-source earnings and rating event proxies are treated as derived risk
  signals rather than as authoritative paid feeds
