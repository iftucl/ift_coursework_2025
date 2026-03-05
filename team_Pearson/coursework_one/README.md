# Team Pearson - Coursework One (CW1)

End-to-end data pipeline for structured factors (`source_a`) and news-derived factors (`source_b`), with:
- PostgreSQL as factor source of truth
- MinIO as raw lake/replay layer
- MongoDB as supplementary news search/index layer

## 1. Quick Run

Run in this exact order:

```bash
# 1) repo root
cd <repo-root>
docker compose up -d postgres_db mongo_db miniocw minio_client_cw

# 2) coursework folder
cd team_Pearson/coursework_one
cp .env.example .env
# set ALPHA_VANTAGE_API_KEY in .env
poetry install
set -a; source .env; set +a

# 3) init DB + seed universe
poetry run python scripts/init_db.py

# 4) run one end-to-end job
poetry run python Main.py --run-date 2026-03-05 --frequency daily --backfill-years 1 --company-limit 5

# 5) verify in PostgreSQL
docker exec -i postgres_db_cw psql -U postgres -d postgres -c \
"select run_id, run_date, status, rows_written from systematic_equity.pipeline_runs order by started_at desc limit 5;"
```

## 2. What This Repo Runs

Main pipeline stages (`Main.py`):
1. Scheduling / run context
2. Universe selection from PostgreSQL
3. Extraction (`source_a`, `source_b`)
4. Normalize + quality checks
5. Upsert atomic records into PostgreSQL
6. Build and upsert final factors
7. Audit/metadata snapshots
8. Mongo news indexing by default (best-effort, disable with `--no-index-mongo`)

Wrapper script (`scripts/run_pipeline_and_index.py`):
- Runs `Main.py` only; Mongo indexing is handled inside `Main.py` (enabled by default, disable with `--no-index-mongo`).

## 3. Storage Responsibilities

| Layer | Role | Example Datasets |
|---|---|---|
| PostgreSQL | Structured factor source of truth, upsert target, audit trail | `systematic_equity.factor_observations`, `financial_observations`, `pipeline_runs` |
| MinIO | Raw/replay lake objects from extractors | `raw/source_a/...`, `raw/source_b/...` |
| MongoDB | Rebuildable serving/search index for news | `ift_cw.news_articles` |

## 4. Project Layout

```text
team_Pearson/coursework_one/
├── Main.py
├── config/
│   ├── conf.yaml
├── modules/
│   ├── db/            # DB engine, models, universe selection
│   ├── input/         # source_a/source_b extractors
│   ├── output/        # normalize, quality, load, audit, metadata
│   ├── transform/     # final factor construction
│   └── utils/         # args/env/mongo helpers
├── scripts/
│   ├── init_db.py
│   ├── seed_universe_from_sqlite.py
│   ├── run_pipeline_and_index.py
│   ├── run_scheduled_pipeline.py
│   ├── index_news_to_mongo.py
│   ├── search_news.py
│   ├── validate_pipeline_data.py
│   ├── verify_minio.sh
│   └── manage_universe_overrides.py
├── sql/
│   └── init.sql
├── tests/
└── docs/               # Sphinx docs source at docs/sphinx/source, HTML output at docs/sphinx/build/html
```

## 5. Prerequisites

- Python `3.11`
- Poetry
- Docker Desktop
- Repo root compose file at `ift_coursework_2025 .../docker-compose.yml`

Important:
- Run `docker compose ...` in repository root, not inside `coursework_one`.
- Run `poetry ...` inside `team_Pearson/coursework_one` (where `pyproject.toml` is).

## 6. Environment Setup

```bash
cd team_Pearson/coursework_one
cp .env.example .env
# set ALPHA_VANTAGE_API_KEY in .env
poetry install
set -a; source .env; set +a
```

Defaults in `.env.example` are aligned with root compose:
- PostgreSQL `localhost:5439`
- MongoDB `localhost:27019`
- MinIO `localhost:9000`

## 7. 10-Minute Runbook (First Successful Run)

### 1) Start infra (repo root)

```bash
cd <repo-root>
docker compose up -d postgres_db mongo_db miniocw minio_client_cw
```

### 2) Initialize PostgreSQL schema + seed universe

```bash
cd team_Pearson/coursework_one
set -a; source .env; set +a
poetry run python scripts/init_db.py
```

`init_db.py` does:
1. Apply `sql/init.sql` via `docker exec ... psql`
2. Seed `systematic_equity.company_static` from `000.Database/SQL/Equity.db`

### 3) Run one end-to-end pipeline job

Example: 1 year, 5 companies

```bash
poetry run python Main.py --run-date 2026-03-05 --frequency daily --backfill-years 1 --company-limit 5
```

### 4) Verify load result

```bash
docker exec -i postgres_db_cw psql -U postgres -d postgres -c \
"select run_id, run_date, status, rows_written from systematic_equity.pipeline_runs order by started_at desc limit 5;"

docker exec -i postgres_db_cw psql -U postgres -d postgres -c \
"select count(*) from systematic_equity.factor_observations;"
```

## 8. Core CLI Commands

### Main pipeline

```bash
poetry run python Main.py --run-date 2026-03-05 --frequency daily
poetry run python Main.py --run-date 2026-03-05 --frequency daily --dry-run
poetry run python Main.py --run-date 2026-03-05 --frequency daily --enabled-extractors source_a,source_b
poetry run python Main.py --run-date 2026-03-05 --frequency daily --no-index-mongo
```

### Wrapper run (orchestration helper)

```bash
poetry run python scripts/run_pipeline_and_index.py --run-date 2026-03-05 --frequency daily
# disable mongo indexing
poetry run python scripts/run_pipeline_and_index.py --run-date 2026-03-05 --frequency daily --no-index-mongo
```

### Scheduled wrapper

```bash
# default schedule mode: daily only
poetry run python scripts/run_scheduled_pipeline.py

# print plan only
poetry run python scripts/run_scheduled_pipeline.py --plan-only

# force frequencies for replay
poetry run python scripts/run_scheduled_pipeline.py --run-date 2026-03-05 --only daily,weekly,monthly,quarterly
```

## 9. Mongo News Search Layer

Role:
- MinIO raw is source of truth
- Mongo `news_articles` is derivable serving/search index

### Rationale for a SQL-Centric Factor Storage Strategy

- Factor master data stays in PostgreSQL as the source of truth (constraints, idempotent upsert, consistent schema).
- Typical factor queries are relational/time-series (`symbol`, `factor_name`, `observation_date`), which are already covered by SQL indexes.
- Full-factor indexing in Mongo would add write amplification and index maintenance cost with limited benefit for the current query path.
- Therefore Mongo is used as a supplementary news search/index layer, not the primary factor store.

### Build/rebuild Mongo index

```bash
poetry run python scripts/index_news_to_mongo.py --run-date 2026-03-05 --since 2026-01-01 --until 2026-03-05
```

### Search indexed news

```bash
poetry run python scripts/search_news.py --q "earnings surprise" --symbol AAP --from 2026-01-01 --to 2026-03-05 --limit 20
```

### Mongo index set created by script

- text: `title + summary`
- time: `time_published`
- symbol: `symbols`
- symbol+time: `symbols + time_published(desc)`
- sparse unique: `url`
- run: `last_seen_run_date`
- run+time: `last_seen_run_date + time_published(desc)`

## 10. PostgreSQL Schema Highlights

Main tables from `sql/init.sql`:
- `systematic_equity.factor_observations`
- `systematic_equity.financial_observations`
- `systematic_equity.pipeline_runs`
- `systematic_equity.company_universe_overrides`
- metadata/lineage/quality tables

`factor_observations` key/index strategy:
- unique key: `(symbol, observation_date, factor_name)`
- performance indexes:
  - `(symbol)`
  - `(observation_date)`
  - `(symbol, factor_name, observation_date)`
  - `(factor_name, observation_date)`

## 11. Database Query Examples (AAP)

### PostgreSQL (factors)

Run in pgAdmin Query Tool (or any SQL client connected to PostgreSQL):

```sql
-- AAP factors on one date
select symbol, observation_date, factor_name, factor_value, source
from systematic_equity.factor_observations
where symbol = 'AAP'
  and observation_date = '2026-03-04'
order by factor_name;
```

### MongoDB (news index)

Run in Mongo UI (Compass or container `mongosh`) on DB `ift_cw`, collection `news_articles`:

```javascript
// count all indexed news
db.news_articles.countDocuments({})

// latest 20 AAP news docs
db.news_articles.find(
  { symbols: "AAP" },
  { _id: 0, title: 1, time_published: 1, url: 1, symbols: 1 }
).sort({ time_published: -1 }).limit(20)
```

## 12. Data and Ops Utilities

### Validate loaded data

```bash
poetry run python scripts/validate_pipeline_data.py --tolerance 1e-6
```

### Verify MinIO raw objects

```bash
./scripts/verify_minio.sh 2026-03-05 AAP
```

### Manage dynamic universe overrides

```bash
poetry run python scripts/manage_universe_overrides.py set --symbol AAP --action include --reason "manual include"
poetry run python scripts/manage_universe_overrides.py set --symbol AAL --action exclude --reason "temporary exclude"
poetry run python scripts/manage_universe_overrides.py list
```

## 13. Final Quality Check (Pre-submit)

Run from `team_Pearson/coursework_one`:

```bash
poetry run pytest -q
poetry run pytest
poetry run flake8 .
poetry run bandit -r modules Main.py
VENV_PATH=$(poetry env info -p) && HOME=/tmp "$VENV_PATH/bin/safety" check -r poetry.lock
cd docs/sphinx && poetry run make html
cd ../..
poetry run python scripts/validate_pipeline_data.py --tolerance 1e-6
```

Notes:
- `pytest` coverage threshold is enforced by config (`>=80%`).
- In this workflow, `safety check` verifies `poetry.lock` without interactive login.
- `safety scan` is the newer command but requires Safety account login/registration (interactive prompt).
- If you need non-interactive coursework checks, use `check`.

## 14. Common Pitfalls

1. `Poetry could not find pyproject.toml`
- Cause: running `poetry` in repo root.
- Fix: `cd team_Pearson/coursework_one` first.

2. MinIO objects unexpectedly missing
- `minio_client_cw` bootstrap recreates bucket `csreport`.
- Re-running/restarting it can wipe previously written objects.

3. Docker service not reachable
- Ensure Docker Desktop is running.
- Check containers:

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

## 15. Documentation Site

Build and open Sphinx docs:

```bash
cd docs/sphinx
poetry run make html
# output: docs/sphinx/build/html/index.html
```
