# Installation Guide

## Scope

This guide installs the **full Team Pearson platform**:

- `CW1` ingestion and raw/curated storage
- `CW2` feature generation, portfolio construction, recommendation, backtest,
  analysis, and report generation
- Airflow orchestration
- Kafka event fan-out
- Sphinx documentation build

## Prerequisites

- Python `3.11`
- Poetry
- Docker Desktop or a local Docker daemon

## 1. Configure environment variables

Run from `team_Pearson/coursework_one`:

```bash
cp .env.example .env
```

Required or commonly used settings:

- `FINNHUB_API_KEY`
- `ALPHA_VANTAGE_API_KEY` for historical Source B rebuilds
- PostgreSQL, MongoDB, MinIO, and Redis defaults from `.env.example`

For downstream reproducibility, note that the platform can replay archived raw
history even when a paid Alpha Vantage workflow is unavailable.

## 2. Start platform services

Run from repository root:

```bash
docker compose \
  -f docker-compose.yml \
  -f team_Pearson/coursework_one/docker-compose.pearson.override.yml \
  up -d postgres_db mongo_db miniocw minio_client_cw team_pearson_redis kafka_cw airflow_cw cw2_kafka_audit_consumer
```

This starts:

- PostgreSQL on `localhost:5439`
- MongoDB on `localhost:27019`
- MinIO API on `localhost:9000`
- MinIO console on `localhost:9001`
- Redis on `localhost:6380`
- Kafka on `localhost:9092`
- Airflow UI on `localhost:8081`

The `cw2_kafka_audit_consumer` service keeps Kafka lag snapshots and consumer
acknowledgements current between scheduled DAG runs.

## 3. Install Python dependencies

```bash
cd team_Pearson/coursework_one
poetry install
set -a; source .env; set +a
```

The shared Poetry environment is used for:

- `CW1`
- `CW2`
- Sphinx builds
- local smoke tests

## 4. Initialize PostgreSQL schema and static universe

```bash
poetry run python scripts/init_db.py
```

This applies `sql/init.sql` and seeds
`systematic_equity.company_static`.

## 5. Optional historical raw replay

If archived raw news files already exist locally and need to be restored into
MinIO:

```bash
poetry run python scripts/import_raw_news_to_minio.py
```

This is the preferred reproducibility route when historical API backfill is not
being re-executed from scratch.

## 6. Manual platform smoke tests

### CW1 ingest

```bash
poetry run python Main.py --run-date 2026-04-13 --frequency daily --dry-run
```

### CW2 operate flow

```bash
cd ../coursework_two
../coursework_one/.venv/bin/python Main.py --mode operate --run-date 2026-04-14 --company-limit 70
```

### CW2 backtest and analysis

```bash
../coursework_one/.venv/bin/python Main.py --mode backtest-and-analyse --run-date 2026-04-14
```

### CW2 report generation

```bash
../coursework_one/.venv/bin/python Main.py --mode report --run-id <existing_run_id>
```

## 7. CW2 quality gate, testing, and coverage

`CW2` does not maintain a separate Poetry project, so the canonical
CW2 quality gate runs through the shared `CW1` Poetry environment
while using checked-in `CW2` configuration for tests and coverage.

Run the full `CW2` gate from the repository root:

```bash
team_Pearson/coursework_two/scripts/run_quality_checks.sh
```

This command runs `poetry check`, `black --check --line-length 100`, `isort
--check --profile black --line-length 100`, `flake8`, `bandit`, and the full
`pytest` coverage gate. To include the shared Sphinx documentation build in the
same command:

```bash
team_Pearson/coursework_two/scripts/run_quality_checks.sh --docs
```

Dependency vulnerability scanning is available as an explicit security audit:

```bash
team_Pearson/coursework_two/scripts/run_quality_checks.sh --with-safety --skip-tests
```

Safety scans the full shared Poetry environment, including Airflow and
developer-tooling dependencies, so it is opt-in rather than a default
reproducibility blocker.

For targeted debugging, the equivalent direct pytest command is:

```bash
cd team_Pearson/coursework_one
poetry run pytest -c ../coursework_two/pytest.ini ../coursework_two/tests/
```

The checked-in pytest configuration:

- keeps discovery and `.pytest_cache` under `coursework_two`
- measures coverage for the `CW2` application package under `../coursework_two`
- keeps `Main.py`, `modules/`, and production-facing `scripts/` inside the
  coverage denominator
- omits development/offline sweep materialisation, sweep scoring, and CSV export
  utilities that are not part of the formal runtime or reproduction path
- enforces `--cov-fail-under=80`

## 8. Build Sphinx documentation

Run from `team_Pearson/coursework_one`:

```bash
poetry run python scripts/build_sphinx_docs.py --clean
```

This shared Sphinx site documents the combined `CW1 + CW2` platform. The source
tree lives under `docs/sphinx/source`.

Output is generated under:

- `docs/sphinx/build/html`

The shared `API Reference` page is autodoc-backed, so module and function
docstrings remain part of the maintained documentation surface rather than
private code comments only.

## 9. Airflow verification

After containers start, Airflow should load:

- `cw1_pipeline_and_docs`
- `cw2_backtest_analysis_report`
- `cw2_monthly_snapshot_backfill`

The recurring DAG `cw1_pipeline_and_docs` includes automated Sphinx generation
and month-end gated CW2 operation.

For the frozen latest CW2 reference run and exact bundle-based reproduction
workflow, continue with `team_Pearson/coursework_two/repro/README.md`.
