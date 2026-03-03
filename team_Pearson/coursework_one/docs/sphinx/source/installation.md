# Installation Guide

## Prerequisites
- Python 3.11+
- Poetry 2.x
- Docker Desktop with Docker Compose

## 1. Start shared infrastructure
Run from repository root:

```bash
cd /Users/celiawong/Desktop/ift_coursework_2025
docker compose up -d postgres_db mongo_db miniocw minio_client_cw
```

This starts:
- PostgreSQL: `localhost:5439`
- MongoDB: `localhost:27019`
- MinIO API: `localhost:9000`
- MinIO Console: `localhost:9001`

## 2. Install project dependencies

```bash
cd team_Pearson/coursework_one
poetry install
```

## 3. Initialize database schema

```bash
poetry run python scripts/init_db.py
```

This applies `sql/init.sql` and seeds `systematic_equity.company_static`.

## 4. Optional smoke run

```bash
poetry run python Main.py --run-date 2026-02-14 --frequency daily --dry-run
```

## 5. Verify quality gates

```bash
poetry run pytest -q
poetry run bandit -r modules Main.py scripts
VENV_PATH=$(poetry env info -p) && HOME=/tmp "$VENV_PATH/bin/safety" check -r poetry.lock
```

## 6. Build docs

```bash
cd docs/sphinx
poetry run make html
```

Generated HTML entry point:
`docs/sphinx/build/html/index.html`
