# Usage Instructions

## Core Manual Commands

### CW1 upstream pipeline

```bash
# single upstream run
poetry run python Main.py --run-date 2026-04-13 --frequency daily

# dry run
poetry run python Main.py --run-date 2026-04-13 --frequency daily --dry-run

# selected extractors only
poetry run python Main.py --run-date 2026-04-13 --frequency daily --enabled-extractors source_a,source_b

# scheduler-facing wrapper
poetry run python scripts/run_scheduled_pipeline.py --run-date 2026-04-13 --only daily --plan-only

# validation
poetry run python scripts/validate_pipeline_data.py --tolerance 1e-6

# rebuild Mongo search layer
poetry run python scripts/index_news_to_mongo.py --run-date 2026-04-13 --since 2026-03-01 --until 2026-04-13
```

### CW2 feature and portfolio flow

```bash
cd ../coursework_two

# build CW2 universe screen, first-level factors, composite alpha, and portfolio targets
../coursework_one/.venv/bin/python Main.py --mode features --run-date 2026-04-20

# same feature pipeline, but refresh CW1 upstream first
../coursework_one/.venv/bin/python Main.py --mode features --with-upstream --run-date 2026-04-20

# production-style operated flow
../coursework_one/.venv/bin/python Main.py --mode operate --run-date 2026-04-20

# daily update decision
../coursework_one/.venv/bin/python Main.py --mode update-decision --run-date 2026-04-21

# persisted control-plane monitoring snapshot
../coursework_one/.venv/bin/python Main.py --mode monitor

# publish a formal recommendation
../coursework_one/.venv/bin/python Main.py --mode recommend --run-date 2026-04-20
```

### CW2 backtest, analysis, and report

```bash
# backtest only
../coursework_one/.venv/bin/python Main.py --mode backtest --run-name cw2_bt_demo

# analysis only
../coursework_one/.venv/bin/python Main.py --mode analyse --run-id <backtest_run_id>

# combined backtest and analysis
../coursework_one/.venv/bin/python Main.py --mode backtest-and-analyse --run-name cw2_bt_analysis_demo

# reporting package
../coursework_one/.venv/bin/python Main.py --mode report --run-id <backtest_run_id>

# readiness audit
../coursework_one/.venv/bin/python Main.py --mode audit

# one-command end-to-end chain
../coursework_one/.venv/bin/python Main.py --mode full-run --run-date 2026-04-20

# full workflow: quality -> services -> full strategy/report -> robustness -> web
../coursework_one/.venv/bin/python scripts/full_workflow.py --start-services --serve
```

The full workflow command is the complete demonstration path. It validates the
quality/docs gate, starts or reuses shared services, runs the formal full-chain
strategy/report workflow, refreshes formal robustness evidence surfaces, and
checks the web/API layer.

### CW2 quality gate

```bash
# from the repository root
team_Pearson/coursework_two/scripts/run_quality_checks.sh

# include the shared CW1+CW2 Sphinx documentation build
team_Pearson/coursework_two/scripts/run_quality_checks.sh --docs

# also write HTML coverage under coursework_two/htmlcov
team_Pearson/coursework_two/scripts/run_quality_checks.sh --html-coverage
```

The gate executes through the shared CW1 Poetry project and runs `poetry check`,
`black --line-length 100`, `isort --profile black --line-length 100`, `flake8`,
`bandit`, and `pytest` against the CW2 codebase and checked-in CW2 test
configuration. Add `--with-safety --skip-tests` when dependency vulnerability
scanning of the full shared Poetry environment is required.

## Airflow Operation

Airflow replaces cron in this project.

- UI: `http://localhost:8081`
- recurring DAG: `cw1_pipeline_and_docs` at `06:00 UTC`
- scheduled monthly DAGs:
  - `cw2_monthly_snapshot_backfill` at `09:30 UTC` on calendar day `1`
  - `cw2_backtest_analysis_report` at `11:30 UTC` on calendar day `1`

### Main task chains

`cw1_pipeline_and_docs`

1. run scheduled `CW1` pipeline wrapper
2. validate curated PostgreSQL data
3. build Sphinx HTML
4. materialize the daily `CW2` update decision
5. trigger rebalance-anchor-gated `CW2 operate` when applicable

`cw2_monthly_snapshot_backfill`

1. backfill historical month-end `portfolio_target_positions`
2. run post-backfill readiness audit
3. audit Kafka event processing state
4. clean up stage context

`cw2_backtest_analysis_report`

1. run preflight readiness audit
2. run stored-strategy backtest
3. materialize analysis outputs
4. render database-backed report artifacts
5. verify the regenerated summary against the tracked reference contract
6. audit Kafka event processing state
7. clean up stage context

### Manual trigger examples

```bash
docker exec airflow_cw airflow dags trigger cw1_pipeline_and_docs
docker exec airflow_cw airflow dags trigger cw2_monthly_snapshot_backfill
docker exec airflow_cw airflow dags trigger cw2_backtest_analysis_report
```

## Kafka Operation

Kafka is optional, but when enabled it complements the batch pipeline with event fan-out.

Published topics currently include:

- `cw1.news.structured.v1`
- `cw1.event.proxies.v1`
- `cw2.risk.actions.requested.v1`
- `cw2.risk.actions.executed.v1`
- `platform.runs.status.v1`

Kafka is not the canonical source of truth. SQL and MinIO remain authoritative.
Consumer acknowledgements, dead letters, and lag snapshots are persisted back to
SQL through the `cw2_kafka_audit_consumer` service and on-demand audit tasks.

## Documentation Build

```bash
poetry run python scripts/build_sphinx_docs.py --clean
```

The Sphinx source lives under `team_Pearson/coursework_one/docs/sphinx/source`,
but the generated site documents the shared `CW1 + CW2` platform rather than a
CW1-only subset.

Generated HTML lives at `docs/sphinx/build/html`.

For the current formal CW2 reference run and frozen exact-reproduction workflow,
see `team_Pearson/coursework_two/repro/README.md`.
