# Team Pearson - Coursework One (CW1)

## Branch
Work on: `feature/coursework_one_Team_04_Pearson`

## Folder rule
All deliverables must live under:
`team_Pearson/coursework_one/`

Do not commit changes outside this folder (e.g., `000.Database`).

## Quickstart (local)
From repository root:

1) If Poetry is installed:

```bash
cd team_Pearson/coursework_one
cp .env.example .env
# set ALPHA_VANTAGE_API_KEY in .env (recommended)
poetry install
poetry run python Main.py --run-date 2026-02-14 --frequency daily --dry-run
```

2) Minimal run without Poetry (for skeleton smoke check):

```bash
cd team_Pearson/coursework_one
python Main.py --run-date 2026-02-14 --frequency daily --dry-run
python -m pytest tests -q
```

## Container bootstrap (minimal)
Mandatory rule:
- Run `docker compose ...` only in repository root `ift_coursework_2025/`.
- Do not run `docker compose` inside `team_Pearson/coursework_one/`.

Use the repository root `docker-compose.yml` as shared infra. From repo root:

```bash
cd ift_coursework_2025
docker compose up -d postgres_db mongo_db miniocw minio_client_cw
```

Important MinIO behavior from teacher compose:
- `minio_client_cw` includes `mc rm -r --force minio/csreport` during bootstrap.
- Restarting `minio_client_cw` recreates bucket `csreport`, so previously written objects are removed.
- If you see object count drop (for example back to `48 objects`), first check whether `minio_client_cw` restarted.

## Standard run sequence (copy/paste)
Run exactly in this order:

```bash
# 1) Start infra in repo root
cd ift_coursework_2025
docker compose up -d postgres_db mongo_db miniocw minio_client_cw

# 2) Run app and tests in coursework_one
cd team_Pearson/coursework_one
cp .env.example .env
# set ALPHA_VANTAGE_API_KEY in .env (recommended)
poetry install
poetry run python Main.py --run-date 2026-02-14 --frequency daily --dry-run
poetry run pytest tests -q
```

If universe tables are missing, seed from the teacher SQLite file (no edits to `000.Database`):

```bash
cd team_Pearson/coursework_one
poetry run python scripts/seed_universe_from_sqlite.py
```

Recommended first-time DB initialization (no compose parameter changes):

```bash
cd team_Pearson/coursework_one
poetry run python scripts/init_db.py
```

This project-level initializer does two steps:
1. Applies `sql/init.sql` into running `postgres_db_cw` via `docker exec`.
2. Seeds `systematic_equity.company_static` from `000.Database/SQL/Equity.db`.

Data validation (date-type consistent checks):

```bash
cd team_Pearson/coursework_one
poetry run python scripts/validate_pipeline_data.py --tolerance 1e-6
```

The validator normalizes date columns on both sides to `date` type before merge/filter checks.


Services and local ports from current compose:
- PostgreSQL: `localhost:5439` -> container `5432`
- MongoDB: `localhost:27019` -> container `27017`
- MinIO API: `localhost:9000` (Console: `localhost:9001`)

## pgAdmin (optional UI) and common issues
pgAdmin is optional for marking/verification. All required database checks can be performed via `psql` (see below). However, if you prefer a UI, the repo root compose exposes pgAdmin at:

- pgAdmin UI: `http://localhost:5051/login`
- Login (from compose defaults): `admin@admin.com` / `root`

### How to register the coursework Postgres server in pgAdmin
pgAdmin runs *inside a container*, so it must connect to Postgres using the Docker network address and the container port:

- **Host name/address:** `postgres_db`
- **Port:** `5432` (container port)
- **Maintenance database:** `postgres`
- **Username:** `postgres`
- **Password:** `postgres`

> Note: `localhost:5439` is the host-machine mapping and is used by local tools (Python/psql/DBeaver) running on your Mac/Windows host, not by pgAdmin inside Docker.

### If pgAdmin shows CSRF/session errors or infinite loading
Some environments (especially on macOS with bind mounts) may experience pgAdmin session/CSRF issues (e.g., “CSRF session token is missing”) or a stuck loading screen. Use the following reset procedure **without modifying the teacher `docker-compose.yml`**:

1) Stop pgAdmin from the repo root:

```bash
cd /Users/celiawong/Desktop/ift_coursework_2025
docker compose stop pgadmin
```

2) Reset pgAdmin local state directory and permissions (repo root):

```bash
cd /Users/celiawong/Desktop/ift_coursework_2025
rm -rf pgadmin-data
mkdir -p pgadmin-data
chmod -R 777 pgadmin-data
docker compose up -d pgadmin
```

3) Re-open `http://localhost:5051/login` (avoid going directly to `/browser/`), log in again, then re-register the server.

### Advanced: pin pgAdmin to a stable version using a local override (DO NOT COMMIT)
If pgAdmin still fails due to a pgAdmin-internal error (HTTP 500 in `pg_admin_cw` logs), you may pin pgAdmin to a stable tag *locally* using a Docker Compose override file. This does **not** modify the teacher file and should not be committed.

Create (or update) `ift_coursework_2025/docker-compose.override.yml` with:

```yaml
services:
  pgadmin:
    image: dpage/pgadmin4:8
    volumes:
      - ./pgadmin-data:/var/lib/pgadmin
```

Then restart:

```bash
cd /Users/celiawong/Desktop/ift_coursework_2025
docker compose rm -sf pgadmin
docker compose up -d pgadmin
```

This override is purely for local convenience; grading and CI do not require pgAdmin.

Docker-aligned defaults used by this project (single source: repo root `docker-compose.yml`):
- `POSTGRES_HOST=localhost`
- `POSTGRES_PORT=5439`
- `POSTGRES_DB=postgres` (compose does not set `POSTGRES_DB`, default DB is `postgres`)
- `POSTGRES_USER=postgres`
- `POSTGRES_PASSWORD=postgres`
- `MONGO_HOST=localhost`
- `MONGO_PORT=27019`
- `MONGO_DB=ift_cw` (project default; compose does not configure Mongo auth)
- `MINIO_ENDPOINT=localhost:9000`
- `MINIO_ACCESS_KEY=ift_bigdata`
- `MINIO_SECRET_KEY=minio_password`
- `MINIO_BUCKET=csreport`

## Dynamic universe add/remove (without editing teacher DB files)
This project supports dynamic universe overrides in your own schema table:
- `systematic_equity.company_universe_overrides`
- columns: `symbol`, `action(include|exclude)`, `is_active`, `reason`, `updated_at`

`get_company_universe()` behavior:
- base universe from teacher table (`company_static` / fallback `equity_static`)
- apply active `exclude` overrides (remove from run universe)
- apply active `include` overrides (add into run universe)

Manage overrides:
```bash
cd team_Pearson/coursework_one

# add a symbol into universe
poetry run python scripts/manage_universe_overrides.py set --symbol NVDA --action include --reason "manual include"

# exclude a symbol from universe
poetry run python scripts/manage_universe_overrides.py set --symbol AAL --action exclude --reason "temporary removal"

# disable an override without deleting it
poetry run python scripts/manage_universe_overrides.py set --symbol AAL --action exclude --is-active false --reason "reactivated"

# list overrides
poetry run python scripts/manage_universe_overrides.py list

# remove an override row
poetry run python scripts/manage_universe_overrides.py remove --symbol AAL
```

MinIO bucket initialization behavior from compose:
- `minio_client_cw` runs `mc rm -r --force minio/csreport` then `mc mb minio/csreport`.
- This means bucket `csreport` is recreated by compose bootstrap (not manually created in app setup docs).

Optional local-only safety override (do not edit teacher compose):
- Use repo root `docker-compose.override.yml` to keep bucket contents by default:
  - `minio_client_cw`: remove auto-delete, keep `mc mb --ignore-existing`.
  - `miniocw`: mount `./minio-data:/data` for persistence across container rebuilds.
  - `minio_reset_cw` (manual profile): explicit reset service when you really need clean state.
- Manual reset command:

```bash
cd /Users/celiawong/Desktop/ift_coursework_2025
docker compose --profile manual-reset run --rm minio_reset_cw
```

MinIO client compatibility note (do not modify teacher `docker-compose.yml`):
- Some environments use a newer `minio/mc` where legacy `mc config host add` is no longer recognized.
- If you see `mc: <ERROR> 'config' is not a recognized command`, use this one-off compatible reset command:

```bash
cd /Users/celiawong/Desktop/ift_coursework_2025
docker run --rm --entrypoint /bin/sh --network ift_coursework_2025_iceberg_net minio/mc -c \
"mc alias set minio http://miniocw:9000 ift_bigdata minio_password && \
mc rm -r --force minio/csreport || true && \
mc mb --ignore-existing minio/csreport && \
mc anonymous set public minio/csreport"
```

Configuration precedence:
- Pipeline behavior parameters (`frequency`, `backfill_years`, `company_limit`, `enabled_extractors`) use:
  1. CLI arguments
  2. OS env (including values loaded from `.env`)
  3. `config/conf.yaml` defaults
  4. built-in defaults
- Connection/secrets (for example `POSTGRES_*`, `MONGO_*`, `MINIO_*`, API keys) use:
  1. OS env
  2. `.env`
  3. `config/conf.yaml` defaults
- `.env` is loaded by entry scripts via `modules/utils/env.py` with non-override semantics for existing OS env.
- Alpha Vantage key resolver order:
  1. `ALPHA_VANTAGE_API_KEY`
  2. `ALPHA_VANTAGE_KEY`
  3. (legacy compatibility only) `config/conf.yaml` key field if present
- Placeholder values (`YOUR_KEY`, `YOUR_API_KEY_HERE`, empty) are treated as missing.

Environment template for local runtime:
- `team_Pearson/coursework_one/.env.example`

Poetry metadata warning note:
- `poetry check` may emit deprecation warnings for `tool.poetry.*` metadata.
- This does not affect current execution (`poetry install`, pipeline run, tests, or grading workflow).
- For coursework stability, we keep the current format now and can migrate to PEP 621 `[project]` metadata in a future maintenance pass.

If needed, create your local env file:

```bash
cd team_Pearson/coursework_one
cp .env.example .env
```

## CLI parameters
- `--run-date` (required): decision date in `YYYY-MM-DD`
- `--frequency` (required): schedule/output mode `daily|weekly|monthly|quarterly|annual`
- `--backfill-years` (optional): rolling lookback window in years (for example `1` = previous 12 months from `run_date`)
- `--company-limit` (optional): universe size cap, default from config
- `--dry-run` (optional): run pipeline without final load
- `--enabled-extractors` (optional): comma-separated extractor list, e.g. `source_a` or `source_a,source_b`

Frequency semantics (unified):
- Atomic ingestion frequency is fixed to daily collection checks (market/news daily, financial upsert by `report_date` when new filings appear).
- `--frequency` controls scheduling window labels and derived-factor output sampling points.
- Financial raw cadence remains encoded by `financial_observations.period_type` (`quarterly`, etc.) and is not controlled by `--frequency`.

## Extractor switches
Default extractor selection is configured in:
- `config/conf.yaml` -> `pipeline.enabled_extractors`
- `config/conf.yaml.example` -> `pipeline.enabled_extractors`

Default is:
```yaml
pipeline:
  enabled_extractors:
    - source_a
    - source_b
```

CLI can override config:
```bash
poetry run python Main.py --run-date 2026-02-14 --frequency daily --dry-run --enabled-extractors source_a,source_b
```

## Source A provider strategy
`source_a` uses a dual-provider design:
- Primary provider: Alpha Vantage (paid API)
- Fallback provider: yfinance (enabled when Alpha Vantage fails)
- Optional replay cache: MinIO raw payload reuse via `source_a.use_cache`

Config keys:
```yaml
api:
  alpha_vantage_key: "YOUR_KEY"
source_a:
  primary_source: alpha_vantage
  enable_yfinance_fallback: true
  use_cache: true
```

Implemented technical factors (daily):
- `momentum_1m`: `(Price_t / Price_{t-20}) - 1`
- `volatility_20d`: rolling 20-day standard deviation of daily returns
- Rule: if history has fewer than 20 trading days, these observations are dropped.
- `debt_to_equity`: daily as-of aligned to the latest available quarterly filing (stepwise series with forward-fill under a staleness limit).
  - Quarterly update cadence for financial atomics; daily as-of output for backtest alignment.

## Current status
Current delivery focus:
- Structured pipeline (`source_a`) is integrated end-to-end (extract -> normalize -> quality -> upsert).
- Unstructured pipeline (`source_b`) is integrated with staged design (raw ingest to MinIO + sentiment transform).
- Final-factor transform stage is integrated: atomic factors in Postgres are read and converted into final factors before upsert.

## Mixed-frequency run examples
```bash
cd team_Pearson/coursework_one
poetry run python Main.py --run-date 2026-02-14 --frequency daily --dry-run
poetry run python Main.py --run-date 2026-02-01 --frequency monthly --dry-run
poetry run python Main.py --run-date 2026-12-31 --frequency annual --dry-run
poetry run python Main.py --run-date 2026-02-14 --frequency daily --dry-run --enabled-extractors source_a,source_b
```

## Auto trigger (daily only)
Use one scheduler entry per day. Default wrapper behavior runs `daily` only:

```bash
cd team_Pearson/coursework_one
poetry run python scripts/run_scheduled_pipeline.py
```

Pipeline orchestration command (manual or scheduler target):

```bash
cd team_Pearson/coursework_one
poetry run python scripts/run_pipeline_and_index.py --run-date 2026-02-14 --frequency daily
```

Mongo index build (best-effort, default enabled):
- enabled by default in `run_pipeline_and_index.py` / `run_scheduled_pipeline.py`
- disable with `--no-index-mongo`
- if Mongo indexing fails, pipeline still returns success

```bash
cd team_Pearson/coursework_one
poetry run python scripts/run_pipeline_and_index.py --run-date 2026-02-14 --frequency daily
```

Trigger rules:
- every day: run `daily` only
- `weekly` / `monthly` / `quarterly`: manual replay only via `--only`

Dry-run plan check:
```bash
cd team_Pearson/coursework_one
poetry run python scripts/run_scheduled_pipeline.py --plan-only
```

Plan check with Mongo indexing enabled by default:
```bash
cd team_Pearson/coursework_one
poetry run python scripts/run_scheduled_pipeline.py --plan-only
```

Plan check with Mongo indexing disabled:
```bash
cd team_Pearson/coursework_one
poetry run python scripts/run_scheduled_pipeline.py --plan-only --no-index-mongo
```

Force specific frequencies for manual replay (not part of cron default):
```bash
cd team_Pearson/coursework_one
poetry run python scripts/run_scheduled_pipeline.py --run-date 2026-04-01 --only daily,weekly,monthly,quarterly
```

Install auto-update cron (run every day at 06:05 host local time by default):
```bash
cd team_Pearson/coursework_one
./scripts/install_auto_update_cron.sh
```

Custom schedule example:
```bash
cd team_Pearson/coursework_one
CRON_SCHEDULE="30 2 * * *" ./scripts/install_auto_update_cron.sh
```

Timezone note:
- `cron` uses the machine local timezone by default (not UTC).
- On DST transitions (for example London switching between GMT/BST), wall-clock run time shifts relative to UTC.

Remove auto-update cron:
```bash
cd team_Pearson/coursework_one
./scripts/uninstall_auto_update_cron.sh
```

## Integration contracts (for roles 3/5/6/7/8)
- `modules.db.get_company_universe(company_limit: int, country_allowlist: list[str] | None = None) -> list[str]`
- `modules.input.extract_source_a(symbols, run_date, backfill_years, frequency, config=None) -> list[dict]`
- `modules.input.extract_source_b(symbols, run_date, backfill_years, frequency, config=None) -> list[dict]`
- `modules.output.normalize_records(records) -> list[dict]`
- `modules.output.run_quality_checks(records) -> dict`
- `modules.output.load_curated(records, dry_run: bool) -> int`
- `modules.transform.compute_final_factor_records(atomic_records, run_date, backfill_years) -> list[dict]`
- `modules.transform.build_and_load_final_factors(run_date, backfill_years, symbols=None, dry_run=False) -> int`

## Extractor B staged design
`extract_source_b` is intentionally pluggable and split into two stages:
1. `ingest_source_b_raw(...)`: raw collection from Alpha Vantage and lake storage in MinIO.
2. `transform_source_b_features(...)`: converts raw payloads into alternative atomic records (`news_sentiment_daily`, `news_article_count_daily`).

Sentiment backend dependency (default):
- `pysentiment2` (LM lexicon) is the default sentiment backend for Source B.
- It is declared in `pyproject.toml` and installed via `poetry install`.
- Runtime logs indicate the active backend:
  - `source_b sentiment_backend=lm_lexicon` (expected default)
  - `source_b sentiment_backend=fallback_lexicon` (only when `pysentiment2` is unavailable)

Extractor B timestamp policy:
```yaml
source_b:
  strict_time: false   # default: fallback missing/invalid article time to month_end and mark timestamp_inferred
                       # true: drop rows with missing/invalid time_published
```

Final daily factors `sentiment_30d_avg` and `article_count_30d` are computed in `modules/transform/factors.py` from atomic records (daily reduction + calendar-day fill + rolling 30D window).

## Search Service (MongoDB)
This project supports a rebuildable MongoDB news-search index:

- Collection: `news_articles`
- One global article per document (deduplicated across symbols)
- MinIO raw remains source of truth; Mongo index is derivable/idempotent
- Scheduler/orchestrator scripts run Mongo indexing by default; disable with `--no-index-mongo`.

### Start infrastructure
From repository root:

```bash
cd /Users/celiawong/Desktop/ift_coursework_2025
docker compose up -d mongo_db miniocw minio_client_cw
```

### Build / rebuild Mongo index from MinIO raw
From `team_Pearson/coursework_one`:

```bash
poetry run python scripts/index_news_to_mongo.py --run-date 2026-02-14 --since 2026-01-01 --until 2026-03-01
```

Or run in one orchestrated command (pipeline first, then index by default):

```bash
poetry run python scripts/run_pipeline_and_index.py --run-date 2026-02-14 --frequency daily
```

Key behavior:
- Dedup `_id` strategy:
  - Primary: `sha256(url)`
  - Fallback when URL is missing: `sha256(source|time_published|normalized_title)`
- Upsert merge strategy:
  - `UpdateOne(..., upsert=True)` + `$addToSet: {tickers: {$each: [...]}}`
  - Ensures global uniqueness and ticker mapping without duplicates
- Field naming note (`tickers` vs `symbol`):
  - Mongo `news_articles` is a search/index serving layer and keeps provider-aligned field name `tickers` (array, one article can map to multiple symbols).
  - PostgreSQL curated tables use `symbol` as the canonical key.
  - Compatibility alias `symbols` is also written in Mongo for query convenience.
- Run-level traceability fields in Mongo documents:
  - `first_seen_run_date`: first run date where this article was indexed
  - `last_seen_run_date`: latest run date where this article was seen
  - `minio_object_keys`: deduplicated raw object key list for source traceability
- Language fields in Mongo documents:
  - `lang`: effective language used by queries
  - `lang_raw`: raw provider language tag when available
  - `lang_inferred`: inferred by `langid` when raw language is missing
  - `lang_source`: `raw|inferred|unknown`
- Required indexes are created automatically:
  - text index: `title + summary`
  - time index: `time_published`
  - sparse unique index: `url`
  - run index: `last_seen_run_date`
  - run+time index: `last_seen_run_date + time_published(desc)`

### Search API via CLI
From `team_Pearson/coursework_one`:

```bash
poetry run python scripts/search_news.py --q "earnings surprise" --ticker AAPL --from 2026-01-01 --to 2026-03-01 --limit 20
```

Supported flags:
- `--q`: full-text query (Mongo `$text`)
- `--ticker`: ticker filter
- `--from`, `--to`: time window
- `--limit`: max rows

Mongo defaults in these scripts:
- default database: `ift_cw` (override with `MONGO_DB` / `config.mongo.database`)
- collection: `news_articles`

## Output and Infra Ownership
- Role 3 (primary): `modules/output/load.py` and SQL persistence rules (e.g., `sql/init.sql` with upsert/index/constraints)
- Role 5 (support): database-schema compatibility checks for SQL changes
- Role 4 (primary): integration-safe management of shared runtime config (`docker-compose.yml`, `.env` conventions)

This split is used to reduce merge conflicts on shared infra files while keeping storage logic owned by the output/database roles.

## Database verification (terminal)
If pgAdmin is unavailable, verify the curated load via `psql`:

```bash
# total rows
docker exec -i postgres_db_cw psql -U postgres -d postgres -c \
"select count(*) from systematic_equity.factor_observations;"

# rows by source
docker exec -i postgres_db_cw psql -U postgres -d postgres -c \
"select source, count(*) from systematic_equity.factor_observations group by source order by count(*) desc;"

# Pipeline run audit (primary DB table)
docker exec -i postgres_db_cw psql -U postgres -d postgres -c \
"select run_id, run_date, status, rows_written, started_at, finished_at from systematic_equity.pipeline_runs order by started_at desc limit 20;"
```

Audit strategy:
- Primary audit source of truth: `systematic_equity.pipeline_runs` (PostgreSQL)
- Secondary debug mirror: `logs/pipeline_runs.jsonl` (local file)

## MinIO raw verification (JSONL)
Quick checks for Source B raw objects (`symbol x month` JSONL):

```bash
cd team_Pearson/coursework_one

# Recommended one-command verifier (auto-detects mc binary path in container)
./scripts/verify_minio.sh 2026-02-14 AAPL
```

Equivalent ad-hoc command (auto-detect `mc` path):

```bash
docker exec -it minio_client_cw sh -lc '
MC_BIN="$(command -v mc || echo /usr/bin/mc)";
$MC_BIN alias set cw http://miniocw:9000 ift_bigdata minio_password >/dev/null &&
$MC_BIN ls --recursive cw/csreport/raw/source_b/news/run_date=2026-02-14/year=2026/month=02/
'
```

## Pre-submit validation checklist
Run from `team_Pearson/coursework_one`:

```bash
poetry run pytest -q
# coverage threshold is enforced by pytest config (>=80%)
poetry run pytest
poetry run bandit -r modules Main.py
# safety check is used here because safety scan requires interactive login in some CLI environments
VENV_PATH=$(poetry env info -p) && HOME=/tmp "$VENV_PATH/bin/safety" check -r poetry.lock
cd docs/sphinx && poetry run make html
```

Bandit / Safety quick run:

```bash
cd team_Pearson/coursework_one
poetry run bandit -r modules Main.py
VENV_PATH=$(poetry env info -p) && HOME=/tmp "$VENV_PATH/bin/safety" check -r poetry.lock
```

Security vulnerability response process:
- Run `bandit` and `safety` before merge/release (and after dependency changes).
- If any vulnerability is reported, open an issue immediately with severity, affected package/module, and scan output.
- For dependency CVEs, patch by updating/removing the package via Poetry (`poetry add ...` / `poetry remove ...`) and refresh lockfile.
- For code-level findings, patch in code and add/adjust tests to prevent regression.
- Re-run `poetry run bandit -r modules Main.py` and `safety` check; merge only after scans are clean.
- Record remediation summary in PR/commit notes for audit traceability.

Docs entry point after build:
- `docs/sphinx/build/html/index.html`

Open the full documentation site from this entry point (left navigation contains all pages):

```bash
cd team_Pearson/coursework_one
open docs/sphinx/build/html/index.html
```
