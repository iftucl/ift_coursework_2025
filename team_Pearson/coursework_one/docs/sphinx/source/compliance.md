# CW1 Compliance Mapping

This page maps the Coursework One brief to concrete, checkable project artifacts.

## 1. Overall Verdict

| Requirement domain | Status | Evidence location |
| --- | --- | --- |
| Infrastructure baseline (MinIO + PostgreSQL + MongoDB) | Met | `docker-compose.yml`, `sql/init.sql`, runtime scripts |
| Ingestion + persistent storage design | Met | `modules/input/*`, `modules/output/*` |
| Flexible run control (`run-date`, frequency) | Met | `Main.py`, `scripts/run_scheduled_pipeline.py` |
| Data quality / validation tooling | Met | `modules/output/quality.py`, `scripts/validate_pipeline_data.py` |
| Metadata management implementation | Met | `modules/output/metadata.py`, metadata tables |
| Testing + quality tooling baseline | Met | `tests/`, `pyproject.toml` |
| Security scanning process | Met | README security section + Bandit/Safety commands |

## 2. Infrastructure Design and Storage

| Requirement | Implementation in this project |
| --- | --- |
| Data lake centered architecture | MinIO raw layer (`raw/source_a/...`, `raw/source_b/...`) with run-date partitioned object paths |
| Structured persistence for factors | PostgreSQL `systematic_equity.factor_observations` |
| Structured persistence for financial metrics | PostgreSQL `systematic_equity.financial_observations` |
| Run audit persistence | PostgreSQL `systematic_equity.pipeline_runs` + local JSONL mirror |
| News search index | MongoDB `ift_cw.news_articles` |

## 3. Flexibility Requirements

| Requirement | Implementation in this project |
| --- | --- |
| Dynamic universe add/remove | Runtime universe from `systematic_equity.company_static` + overrides in `company_universe_overrides` |
| Historical retrieval (>= 5 years) | `backfill_years` parameter and config defaults |
| Regular execution by frequency | `Main.py --frequency` and scheduler wrapper `scripts/run_scheduled_pipeline.py` |
| Run-date parameterization | `--run-date` across main and orchestrator scripts |

## 4. Data Quality and Validation

| Requirement | Implementation in this project |
| --- | --- |
| Data quality checks | `modules/output/quality.py` and `scripts/validate_pipeline_data.py` |
| Pipeline consistency validation | `scripts/validate_pipeline_data.py --tolerance 1e-6` |
| Uniqueness and idempotency | Unique constraints + upsert in load path (`modules/output/load.py`) |
| Quality snapshots for governance | PostgreSQL `systematic_equity.quality_snapshots` |

## 5. Metadata Management

| Requirement | Implementation in this project |
| --- | --- |
| Dataset registry | `systematic_equity.dataset_registry` |
| Schema versioning | `systematic_equity.schema_versions` |
| Lineage tracking | `systematic_equity.lineage_edges` |
| Automated metadata bootstrap | `modules/output/metadata.py::bootstrap_metadata_catalog` |

## 6. Testing and Code Quality

| Requirement | Implementation in this project |
| --- | --- |
| Unit / integration / E2E tests | `tests/` (`test_*_unit.py`, integration and e2e suites) |
| Coverage threshold >= 80% | Pytest config in `pyproject.toml` |
| Lint/format/import checks | `flake8`, `black`, `isort` via Poetry |
| Security scanning | `bandit` and `safety` process documented in README |

## 7. Documentation

| Requirement | Implementation in this project |
| --- | --- |
| Sphinx docs | `docs/sphinx/source` and generated HTML in `docs/sphinx/build/html` |
| Installation / Usage / Module Reference / Architecture | `installation.md`, `usage.md`, `module_reference.md`, `architecture.md` |
| Core code docstrings | Core runtime and module docstrings aligned with Sphinx pages |

## 8. Zero-to-Run Acceptance Commands

Use these commands when demonstrating compliance in a live check:

```bash
poetry run python scripts/init_db.py
poetry run python Main.py --run-date 2026-02-14 --frequency daily
poetry run python scripts/validate_pipeline_data.py --tolerance 1e-6
poetry run pytest -q
poetry run bandit -r modules Main.py scripts
```
