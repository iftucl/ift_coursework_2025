# Team Pearson - Coursework One (CW1)

CW1 now runs as a layered pipeline with:

- PostgreSQL as the curated factor and audit store
- MinIO as the raw/replay lake
- MongoDB as the rebuildable news search layer
- Redis as the shared state store for rate limiting, circuit breaking, and Source B URL deduplication
- Kafka as the optional event bus for structured news, event proxies, and downstream risk-action fan-out
- Airflow as the scheduler and Sphinx automation entrypoint

Current data-source design:

- `source_a`: `yfinance` primary market/fundamental data, `Alpha Vantage` fallback, plus `EDGAR XBRL` supplement
- `source_b`: `Alpha Vantage (historical) + Finnhub (incremental) + Loughran-McDonald sentiment`
- final factors: built from curated atomics already stored in PostgreSQL

Current universe semantics:

- investable universe: loaded from PostgreSQL `systematic_equity.company_static`
- seed source for `company_static`: `000.Database/SQL/Equity.db`
- benchmark series: `market_factors.benchmark_ticker` (canonical shared benchmark; CW2 `backtest.benchmark_ticker` must match)
- country scope: `universe.country_allowlist` defines the upstream parent universe; CW2 may only narrow it

## Configuration Layers

The pipeline has four configuration layers, from highest to lowest priority:

| Layer | File / Source | What it controls | When to use |
| --- | --- | --- | --- |
| **CLI arguments** | `--run-date`, `--frequency`, `--backfill-years`, `--company-limit`, `--enabled-extractors`, `--dry-run` | Per-run overrides | Manual runs, debugging, one-off backfills |
| **Environment variables** | `.env` (loaded via `set -a; source .env; set +a`) | API keys, service endpoints, runtime tuning | Local development, secrets that should not be in config files |
| **Config file** | `config/conf.yaml` | Pipeline defaults (frequency, backfill depth, rate limits, cutoff dates, provider settings) | Team-wide defaults shared via git |
| **Airflow DAG** | `airflow/dags/cw1_pipeline_and_docs.py` plus CW2 DAGs in `airflow/dags/` | Scheduled execution, manual research bundles, and monthly backfill orchestration | Production recurring runs |

CLI arguments override `.env`, which overrides `conf.yaml`. Airflow passes `--run-date {{ ds }}` as a CLI argument to the pipeline.

### Key environment variables (`.env.example`)

| Variable | Purpose | Default |
| --- | --- | --- |
| `FINNHUB_API_KEY` | Finnhub API authentication (incremental news) | _(required)_ |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage API authentication (historical news) | _(required)_ |
| `SOURCE_B_INCREMENTAL_BUFFER_DAYS` | Overlap days for incremental news dedup | `7` |
| `POSTGRES_HOST` / `PORT` / `DB` / `USER` / `PASSWORD` | PostgreSQL connection | `localhost:5439/fift` |
| `MONGO_HOST` / `PORT` / `DB` | MongoDB connection | `localhost:27019/ift_cw` |
| `MINIO_ENDPOINT` / `ACCESS_KEY` / `SECRET_KEY` / `BUCKET` | MinIO connection | `localhost:9000/csreport` |
| `REDIS_HOST` / `PORT` / `DB` / `REQUIRED` | Redis connection and enforcement | `localhost:6380/0` |
| `KAFKA_BOOTSTRAP_SERVERS` / `KAFKA_ENABLED` / `KAFKA_REQUIRED` | Kafka fan-out connectivity and enforcement | `localhost:9092` / `false` / `false` |

### Key config file settings (`conf.yaml`)

| Setting | Purpose | Default |
| --- | --- | --- |
| `pipeline.frequency` | Default run frequency | `daily` |
| `pipeline.backfill_years` | Historical depth for upstream collection (should be at least CW2 `lookback_years`, ideally with extra warm-up buffer) | `5` |
| `pipeline.company_limit` | Universe cap (null = all) | `5` (smoke test) |
| `source_b.av_cutoff_date` | AV/Finnhub routing boundary | `2026-03-01` |
| `finnhub.rate_per_minute` | Finnhub rate limit | `55` |
| `edgar.rate_per_second` | EDGAR rate limit | `8` |

## Quick Start

```bash
# 1) repo root
cd <repo-root>
docker compose \
  -f docker-compose.yml \
  -f team_Pearson/coursework_one/docker-compose.pearson.override.yml up -d \
  postgres_db mongo_db miniocw minio_client_cw team_pearson_redis kafka_cw airflow_cw

# 2) coursework folder
cd team_Pearson/coursework_one
cp .env.example .env
# set FINNHUB_API_KEY and ALPHA_VANTAGE_API_KEY in .env
poetry install
set -a; source .env; set +a

# 3) initialize schema + seed universe
poetry run python scripts/init_db.py

# 4) run one small manual job
poetry run python Main.py --run-date 2026-04-13 --frequency daily --backfill-years 1 --company-limit 5

# 5) build docs manually if needed
poetry run python scripts/build_sphinx_docs.py --clean
```

## CW2 Entry Point

CW2 now also has its own runnable entrypoint at `team_Pearson/coursework_two/Main.py`.

- `coursework_one/Main.py`: full shared pipeline orchestrator
- `coursework_two/Main.py`: CW2-facing entrypoint for feature engineering, risk overlay, and portfolio construction

From `team_Pearson/coursework_two`, markers can either:

```bash
# run CW2 only from existing curated data
../coursework_one/.venv/bin/python Main.py --run-date 2026-04-14 --company-limit 70

# or refresh upstream first, then hand off into CW2
../coursework_one/.venv/bin/python Main.py --with-upstream --run-date 2026-04-14 --company-limit 70
```

Airflow UI:

- URL: `http://localhost:8081`
- DAGs:
  - `cw1_pipeline_and_docs`
  - `cw2_backtest_analysis_report`
  - `cw2_monthly_snapshot_backfill`
- Daily chain: pipeline run -> curated-data validation -> CW2 update decision -> Sphinx HTML build -> month-end-gated CW2 operate

## What Runs Now

`Main.py` is the core orchestrator. It:

1. resolves runtime config
2. loads the universe from PostgreSQL
3. runs `source_a`, `source_b`, and `market_factors`
4. archives raw payloads to MinIO
5. upserts atomic data into PostgreSQL
6. builds final factors
7. writes metadata and audit state
8. best-effort indexes Source B articles into MongoDB

`scripts/run_scheduled_pipeline.py` remains the scheduler-facing CLI entrypoint, but scheduling is now performed by Airflow rather than cron.

## Storage Responsibilities

| Layer | Role | Main datasets |
| --- | --- | --- |
| PostgreSQL | Curated source of truth and audit | `factor_observations`, `financial_observations`, `pipeline_runs` |
| MinIO | Raw/replay archive | `raw/source_a/...`, `raw/source_b/...` |
| MongoDB | Rebuildable search-serving layer | `ift_cw.news_articles` |
| Redis | Shared resilience and dedupe state | circuit breakers, token buckets, `cw1:news:seen_urls:*` |
| Kafka | Optional event fan-out | structured Source B news, event proxies, downstream risk-action events |

## Source B Contract

`source_b` is now fully standardized on `Alpha Vantage + Finnhub + L-M sentiment`.

- Alpha Vantage: ticker-scoped historical news (before `av_cutoff_date`, configurable in `conf.yaml`)
- Finnhub: ticker-scoped incremental news (after cutoff date, free tier)
- date-based routing: `_fetch_provider_articles` automatically selects AV or Finnhub based on the window vs cutoff
- sentiment scoring: Loughran-McDonald lexicon via `pysentiment2`, with a small fallback lexicon if unavailable
- raw storage: monthly JSONL snapshots plus current-month merged views and per-month cursor files in MinIO
- curated atomics:
  - `news_sentiment_daily`
  - `news_article_count_daily`
- optional event fan-out:
  - `cw1.news.structured.v1`
  - `cw1.event.proxies.v1`

## Redis Usage

Redis is now used for three shared runtime controls:

- circuit breaker state for downstream providers
- token-bucket state for provider rate limiting
- per-symbol article URL deduplication across Alpha Vantage and Finnhub

Key implementation notes:

- `REDIS_REQUIRED=true` can be used to fail fast outside tests
- Redis connection settings support `REDIS_URL` or `REDIS_HOST/PORT/DB/PASSWORD`
- the circuit breaker now enforces `half_open_max_calls` correctly
- Redis persistence is enabled in Docker with AOF plus RDB snapshotting

## Airflow and Documentation Automation

Airflow replaces the old cron scripts and now acts as the orchestration layer across both coursework stages.

- DAG file: `airflow/dags/cw1_pipeline_and_docs.py`
- default schedule: daily at `06:00 UTC`
- task chain:
  - `run_daily_pipeline`
  - `validate_curated_data`
  - `run_cw2_update_decision`
  - `build_sphinx_docs`
  - `run_cw2_operate_if_month_end`

Manual Airflow DAGs now cover the heavier CW2 paths as well:

- `airflow/dags/cw2_backtest_analysis_report.py`
  - runs `backtest -> analyse -> report` as one controlled research bundle
- `airflow/dags/cw2_monthly_snapshot_backfill.py`
  - backfills missing month-end `portfolio_target_positions` from already-materialized upstream data

Manual DAG trigger example:

```bash
docker exec -it airflow_cw airflow dags trigger cw1_pipeline_and_docs
```

Sphinx is built by:

```bash
poetry run python scripts/build_sphinx_docs.py --clean
```

Generated HTML entrypoint:

- `docs/sphinx/build/html/index.html`

## Core Commands

```bash
# manual single run
poetry run python Main.py --run-date 2026-04-13 --frequency daily

# dry run
poetry run python Main.py --run-date 2026-04-13 --frequency daily --dry-run

# source subset
poetry run python Main.py --run-date 2026-04-13 --frequency daily --enabled-extractors source_a,source_b

# scheduler-facing wrapper
poetry run python scripts/run_scheduled_pipeline.py --run-date 2026-04-13 --only daily --plan-only

# validation
poetry run python scripts/validate_pipeline_data.py --tolerance 1e-6

# rebuild Mongo news index
poetry run python scripts/index_news_to_mongo.py --run-date 2026-04-13 --since 2026-03-01 --until 2026-04-13

# audit AV/Finnhub transition boundary for duplicate article URLs in Mongo
poetry run python scripts/audit_source_b_boundary.py --since 2026-02-28 --until 2026-03-03

# search indexed news
poetry run python scripts/search_news.py --q "earnings surprise" --symbol AAPL --limit 10

# import legacy AV raw news into MinIO (one-time, no API key needed)
poetry run python scripts/import_raw_news_to_minio.py --source-dir /path/to/source_b/news
```

## Testing

The project uses `pytest` with three layers of tests in `tests/`:

- **Unit tests** (`test_*_unit.py`): individual functions and methods in isolation
- **Integration tests** (`test_pipeline_integration.py`, `test_smoke.py`): interactions between components
- **End-to-end tests** (`test_e2e.py`): full pipeline verification from ingestion to curated output
- **Regression tests** (`test_replay_regression.py`): replay-based consistency checks

Coverage target: **minimum 80%** (enforced via `--cov-fail-under=80` in `pyproject.toml`).

```bash
# run all tests with coverage report
poetry run pytest ./tests/

# run a specific test file
poetry run pytest ./tests/test_source_b_unit.py -v
```

## Code Quality

Linting and formatting are configured in `pyproject.toml` and `.flake8`:

```bash
# linting (flake8)
poetry run flake8 modules/ scripts/ Main.py

# formatting check (black, line-length=100)
poetry run black --check modules/ scripts/ Main.py

# import sorting check (isort, profile=black)
poetry run isort --check modules/ scripts/ Main.py
```

## Security

Vulnerability scanning uses Bandit (static analysis) and Safety (dependency audit):

```bash
# static security scan
poetry run bandit -r modules/ scripts/ -c pyproject.toml

# dependency vulnerability scan
poetry run safety check
```

## Documentation

Documentation is built with Sphinx (source in `docs/sphinx/source/`, output in `docs/sphinx/build/html/`).

All modules, classes, and functions use **Sphinx-style docstrings** (`:param:`, `:type:`, `:returns:`, `:rtype:`).

Sphinx pages include:

- **Installation guide** (`installation.md`)
- **Usage instructions** (`usage.md`)
- **API reference** (`module_reference.md`)
- **Architecture overview** (`architecture.md`)
- **Data implementation** (`data_implementation.md`)
- **Compliance** (`compliance.md`)

```bash
# build HTML documentation
poetry run python scripts/build_sphinx_docs.py --clean

# output entrypoint
open docs/sphinx/build/html/index.html
```

Airflow also builds Sphinx automatically as the last step in the DAG chain (`build_sphinx_docs`).

## Project Layout

```text
team_Pearson/coursework_one/
├── Main.py
├── airflow/
│   └── dags/
├── config/
├── docker/
│   └── airflow/
├── docs/
│   └── sphinx/
├── modules/
│   ├── db/
│   ├── extract/
│   ├── input/
│   ├── output/
│   ├── transform/
│   └── utils/
├── scripts/
├── sql/
└── tests/
```

## Notes

- Run `docker compose ...` from repository root.
- Run `poetry ...` inside `team_Pearson/coursework_one`.
- `scripts/init_db.py` applies `sql/init.sql` and seeds the universe from the teacher SQLite file.
- Airflow replaces cron in this project. The old cron helper scripts have been removed.
