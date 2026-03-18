# Installation Guide

This page covers environment setup and first-time project initialization. For
day-to-day execution commands, scheduler usage, and validation workflows, see
the Usage Instructions page.

## Prerequisites
- Python 3.11+
- Poetry 2.x
- Docker Desktop with Docker Compose

## 1. Start shared infrastructure
Run from repository root:

```bash
cd ift_coursework_2025
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

This auto-creates the coursework database `fift` if needed, applies
`sql/init.sql`, and seeds `systematic_equity.company_static`.

## 4. Optional smoke test

```bash
poetry run python Main.py --run-date 2026-02-14 --frequency daily --dry-run
```

This is only a lightweight startup check. Operational runs, validation, and
inspection commands are documented under Usage Instructions.

## 5. Build docs

```bash
cd docs/sphinx
poetry run make html
```

Generated HTML entry point:
`docs/sphinx/build/html/index.html`
