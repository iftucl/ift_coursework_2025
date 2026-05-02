# Full Run Reproduction

This document records the exact full-run procedure for the current Team Pearson setup.

If the goal is the exact GitHub-clone reproduction of the formal reference
run and its metrics, use `team_Pearson/coursework_two/repro/README.md` instead.
This document remains the live full-chain and fixed-window rerun procedure.

It is written to match the current codebase and current storage policy:

- keep `Source B` raw news history only through `2026-02-28`
- re-collect `Source B` incrementally from `2026-03-01` onward
- clear rerunnable SQL outputs before the full run
- keep static universe and metadata catalog tables
- require PostgreSQL, MinIO, MongoDB, and Redis to be running before the application chain starts

## Minimal Reproduction of the Current Formal Run

For marking or audit purposes, the shortest path to reproduce the current formal
CW2 run is:

1. use the checked-in `team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml`
2. rebuild historical CW2 month-end snapshots for the fixed window
3. run the fixed-window backtest, analysis, and report bundle

This does **not** require re-running the whole upstream pipeline if CW1 curated
history is already materialized in PostgreSQL / MinIO.

For the frozen exact-metric path from a GitHub clone, the expected flow is:

1. restore the latest release bundle with
   `team_Pearson/coursework_two/scripts/restore_repro_bundle.sh`
2. re-render the saved run `6905e84b-9e16-4106-8c0f-cd9ecce56728`
3. verify the generated summary with
   `team_Pearson/coursework_two/scripts/verify_reference_metrics.py`

### Preconditions

The following must already match the project environment:

- PostgreSQL, MinIO, MongoDB, and Redis are running
- `team_Pearson/coursework_one/.env` is present and loadable
- CW1 historical curated data already exists
- CW2 schemas already exist

### Commands

From repo root:

```bash
cd <repo-root>
set -a
source team_Pearson/coursework_one/.env
set +a
```

Rebuild month-end `portfolio_target_positions` snapshots for the saved best configuration.
These are the stored month-end anchors even when the active strategy refresh cadence
is less frequent; off-cycle month-ends may carry forward the previous target set:

```bash
team_Pearson/coursework_one/.venv/bin/python team_Pearson/coursework_two/scripts/backfill_monthly_snapshots.py \
  --start-date 2021-04-01 \
  --end-date 2026-04-20 \
  --company-limit 0 \
  --skip-existing false \
  --refresh-market-factors false \
  --cw1-config team_Pearson/coursework_one/config/conf.yaml \
  --cw2-config team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml
```

Then run the fixed-window backtest, analysis, and report:

```bash
team_Pearson/coursework_one/.venv/bin/python - <<'PY'
from team_Pearson.coursework_two.modules.backtest import run_backtest_from_config
from team_Pearson.coursework_two.modules.analysis import run_analysis_from_config
from team_Pearson.coursework_two.modules.reporting import generate_backtest_report_from_config

config_path = "team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml"
run_id = run_backtest_from_config(
    run_name="cw2_formal_20260420_fund_ra3_s30_t50_repro",
    config_path=config_path,
    config_override={"backtest": {"start_date": "2021-04-20", "end_date": "2026-04-20"}},
)
print("RUN_ID", run_id)
print(run_analysis_from_config(run_id=str(run_id), config_path=config_path))
print(
    generate_backtest_report_from_config(
        run_id=str(run_id),
        config_path=config_path,
        report_name="cw2_formal_fund_ra3_s30_t50_20260420_repro_report",
    )
)
PY
```

### Expected Result

The current formal saved run in this workspace is:

- `run_id`: `6905e84b-9e16-4106-8c0f-cd9ecce56728`
- run name:
  `cw2_formal_20260420_fund_ra3_s30_t50`
- report dir:
  `team_Pearson/coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report`

A correct reproduction against the same materialized upstream history should land
very close to the following metrics:

- total return: about `74.115%`
- annualized return: about `11.940%`
- annualized volatility: about `15.816%`
- Sharpe ratio: about `0.582`
- max drawdown: about `17.131%`
- information ratio vs primary benchmark `SPY`: about `0.126`
- benchmark total return vs `SPY`: about `67.76%`
- excess annualized return vs primary benchmark `SPY`: about `0.844%`
- secondary comparison total return vs `universe_ew`: about `55.282%`
- information ratio vs `universe_ew`: about `0.452`

Small differences inside that range are acceptable as long as the same fixed
window, same configuration, and same materialized upstream history are used.

## One-Command Entry Point

The current codebase now exposes a single full workflow command that wraps the whole flow:

```bash
cd <repo-root>
team_Pearson/coursework_one/.venv/bin/python team_Pearson/coursework_two/Main.py \
  --mode full-run \
  --run-date 2026-04-20 \
  --cw2-config team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml
```

The formal reference path uses the configured full universe. Developers may add
`--smoke-profile`, `--smoke-lookback-years N`, or `--company-limit` only for
local plumbing checks, but smoke-profile and capped runs are not formal
performance evidence and should not be used in the final report. The older
`--quick-*` option names remain accepted as aliases.

That wrapper internally performs:

1. CW1 database init and universe seeding
2. CW2 schema initialization
3. MinIO bucket / Mongo indexes / Kafka topic bootstrap
4. CW1 full upstream refresh
5. CW2 historical month-end snapshot backfill
6. CW2 readiness audit
7. CW2 operate flow
8. CW2 backtest, analysis, and report generation

This command is a **warm-start application entrypoint**, not a full infrastructure bootstrap.

It assumes:

- Docker services are already up
- Redis has already been flushed
- the historical `Source B` archive through `2026-02-28` is already present in MinIO in the canonical layout, or has been imported via Step 0.5

The wrapper does **not** restart Docker services, flush Redis, or convert/import a legacy `Source B` archive from disk. For a true cold start from a fully wiped state, complete the Precondition checklist below, Step 0.25 (runtime readiness + `FLUSHDB`), and Step 0.5 (historical Source B import/conversion) before invoking `--mode full-run`.

The remainder of this document keeps the step-by-step manual equivalent for debugging, reruns, or partial execution.

## Scope

This run targets the current **US equity** universe from `systematic_equity.company_static`.

The pipeline design is:

1. `CW1` full upstream ingestion and factor materialization
2. `CW2` feature generation from curated `CW1` data
3. `CW2` month-end snapshot and operational outputs
4. `CW2` backtest, analysis, and reporting after the history is available

## Precondition

Before running this document, the environment should already be in the cleaned state:

- PostgreSQL rerunnable output tables truncated (if a full wipe removed the tables themselves, Step 0 below will recreate them)
- Redis fully flushed (`FLUSHDB`), including `cw1:news:seen_urls*` dedup sets and any circuit-breaker state keys — a stale OPEN breaker will silently block fresh ingestion
- Mongo `news_articles` collection cleared (indexes are rebuilt by Step 1 `--index-mongo`)
- `MinIO raw/source_a` removed
- `MinIO raw/source_b/news` kept only through `2026-02-28` **and already converted** to the canonical `run_date=YYYY-MM-DD/year=YYYY/month=MM/symbol=XXXX.jsonl` layout expected by the ingestion pipeline — if the legacy archive still sits on local disk in the old layout, run Step 0.5 below to import and convert it before Step 1
- `MinIO raw/source_b/news_current` empty
- `MinIO raw/source_b/news_cursor` empty
- materialization/manifests logs cleared
- `.env` contains `REDIS_URL` and `REDIS_REQUIRED=true` — without `REDIS_REQUIRED=true` the news extractor silently falls back to *no deduplication* when Redis is unreachable, which can cause the historical/incremental boundary to double-ingest
- PostgreSQL, MinIO, MongoDB, Redis, and Kafka containers are expected to be started by default for the formal run; Kafka is still non-blocking at the application level, but the reference environment starts it alongside the other services

## Start Services

From repo root:

```bash
docker compose \
  -f docker-compose.yml \
  -f team_Pearson/coursework_one/docker-compose.pearson.override.yml \
  up -d postgres_db mongo_db miniocw minio_client_cw team_pearson_redis kafka_cw airflow_cw cw2_kafka_audit_consumer
```

If the Airflow container cannot resolve `miniocw` or `kafka_cw`, or if Kafka
audits fail because `kafka-python` is missing, rebuild and recreate the
container so the latest override env and image dependencies are applied:

```bash
docker compose \
  -f docker-compose.yml \
  -f team_Pearson/coursework_one/docker-compose.pearson.override.yml \
  up -d --build --force-recreate miniocw minio_client_cw team_pearson_redis kafka_cw airflow_cw cw2_kafka_audit_consumer
```

## Environment

Use the shared `CW1` virtual environment:

```bash
cd <repo-root>
set -a
source team_Pearson/coursework_one/.env
set +a
```

If `.env` is missing, create it from `.env.example` first and fill the required keys.

## Step 0: Initialize Database Schemas

If the Docker volumes were wiped (not just table truncation), the PostgreSQL database is empty and `systematic_equity.*` tables do not exist. Apply the schema before any ingestion.

Apply the CW1 base schema plus the company universe seed (also re-runs any CW1 migrations):

```bash
team_Pearson/coursework_one/.venv/bin/python team_Pearson/coursework_one/scripts/init_db.py
```

Apply all CW2 schemas (feature, backtest, intraday, ops, recommendation, analysis, reporting):

```bash
for f in team_Pearson/coursework_two/sql/cw2_*.sql; do
  echo "applying $f"
  docker exec -i postgres_db_cw psql -U postgres -d fift < "$f"
done
```

The `full-run` wrapper does this internally; only skip Step 0 if you have already confirmed every `systematic_equity.*` table exists.

## Step 0.25: Confirm Runtime Services Are Ready

Before ingestion, confirm the supporting stores are actually reachable and clean:

```bash
# Redis is alive and empty
docker exec team_pearson_redis redis-cli PING
docker exec team_pearson_redis redis-cli FLUSHDB

# Mongo is reachable
docker exec mongo_db_cw mongosh ift_cw --quiet --eval "db.runCommand({ ping: 1 })"

# REDIS_REQUIRED is actually set — the extractor needs this for correct dedup semantics
grep '^REDIS_REQUIRED=' team_Pearson/coursework_one/.env
```

The full-run wrapper will bootstrap the Kafka topics declared in the active CW2
config if Kafka is reachable. Kafka remains `required: false`, but the formal
reference environment still starts it together with the other stores.

## Step 0.5: Import and Convert Legacy Source B Archive (one-time)

This step is **mandatory** whenever the historical `Source B` archive (through `2026-02-28`) still exists only in the legacy local-disk layout. The script uploads each file to MinIO under the canonical `run_date=YYYY-MM-DD/year=YYYY/month=MM/symbol=XXXX.jsonl` key structure and writes the `news_current` and `news_cursor` markers so the downstream ingester treats those months as already closed.

```bash
team_Pearson/coursework_one/.venv/bin/python team_Pearson/coursework_one/scripts/import_raw_news_to_minio.py \
  --source-dir <path-to-legacy-news-archive> \
  --cutoff-date 2026-03-01
```

After this step, everything strictly earlier than `2026-03-01` is sealed in MinIO with the right layout. Step 1 must then:

- reuse the historical raw archive through `2026-02-28`
- collect only the incremental segment from `2026-03-01` onward
- rebuild Mongo and downstream PostgreSQL sentiment-derived datasets so `Source B` is complete across all stores

## Step 1: CW1 Full Upstream Run

Run the shared upstream pipeline from `CW1`.

Notes:

- `--company-limit 0` is used intentionally. In the current code, `company_limit <= 0` resolves to `None`, which means full universe instead of sample/debug mode.
- `--backfill-years 5` matches the current project default and current coursework target window.
- `--enabled-extractors source_a,source_b,market_factors` makes the active stages explicit instead of relying on config inference.

```bash
team_Pearson/coursework_one/.venv/bin/python team_Pearson/coursework_one/Main.py \
  --config team_Pearson/coursework_one/config/conf.yaml \
  --run-date 2026-04-20 \
  --frequency daily \
  --backfill-years 5 \
  --company-limit 0 \
  --enabled-extractors source_a,source_b,market_factors \
  --index-mongo
```

This run will:

- fetch `Source A` market data with `yfinance` primary and `Alpha Vantage` fallback
- build `Source A` financial payloads with `yfinance` scaffold, `Alpha Vantage` gap fill, and `EDGAR XBRL` authoritative on mapped overlapping core financial metrics
- reuse `Source B` raw archive through `2026-02-28`
- collect `Source B` incrementally from `2026-03-01` onward
- build curated atomics
- build final factors
- build `CW2` feature tables from the curated store
- rebuild the Mongo news index

Terminology note:

- `CW1 as_of` means extraction/audit date on upstream provider-facing records
- `CW2 as_of_date` means the month-end or scheduled strategy snapshot/decision date
- `CW2 signal_as_of_date` means the latest factor/event signal date used by update-decision monitoring

The names are similar but they should not be treated as interchangeable in SQL checks or report prose.
`CW1 as_of` is an extraction/audit clock, while `CW2 as_of_date` and `CW2 signal_as_of_date` are downstream strategy clocks.

## Step 1.5: Gate Check Before Going Multi-Year

After Step 1 completes, stop and verify the pipeline before paying for the multi-year backfill in Step 2. The Step 1.5 gate has four required parts.

**Quality snapshots must be clean:**

```bash
docker exec postgres_db_cw psql -U postgres -d fift -c "
SELECT run_date, dataset_name, status
FROM systematic_equity.quality_snapshots
WHERE status != 'pass'
ORDER BY run_date DESC
LIMIT 50;
"
```

If any row comes back, **do not proceed to Step 2** — a single `min_scoring_universe` or `min_factor_score_coverage_vs_scoring` fail will silently cascade into empty month-end snapshots and produce the near-zero-NAV symptom seen in prior runs.

**Redis dedup must actually be active** (sanity-check that Source B increments are going through Redis, not the no-dedup fallback):

```bash
docker exec team_pearson_redis redis-cli --scan --pattern 'cw1:news:seen_urls*' | wc -l
docker exec team_pearson_redis redis-cli KEYS 'circuit_breaker:*'
```

The first count should be non-zero after incremental ingestion. The second should be empty (no stuck OPEN breakers).

**Source A/Source B coverage contract must pass** for the latest upstream run:

```bash
docker exec postgres_db_cw psql -U postgres -d fift -c "
SELECT source_name, status, COUNT(*) AS n_symbols
FROM systematic_equity.source_coverage_audit
WHERE run_date = '2026-04-20'
GROUP BY source_name, status
ORDER BY source_name, status;
"
```

For the formal run, `unexpected_missing` must be zero. `realized_empty` is acceptable for symbols with no articles in-window or provider-unavailable historical tickers, but those statuses must be explicit and auditable.

**Historical/incremental Source B boundary audit must pass**:

```bash
team_Pearson/coursework_one/.venv/bin/python team_Pearson/coursework_one/scripts/audit_source_b_boundary.py
```

This is not optional for the formal run. It confirms the reused historical archive and the incremental post-`2026-03-01` flow did not silently duplicate or split the boundary window.

Only after Step 1.5 is clean should you proceed to the full multi-year backfill.

## Step 2: Historical CW2 Month-End Snapshots

Before any multi-month backtest, backfill month-end `portfolio_target_positions`
snapshots. These snapshots remain the stored audit/backtest anchors even when the
active strategy refresh cadence is quarterly or otherwise less frequent than
monthly. In those off-cycle months, the CW2 feature pipeline should carry forward
the prior target set instead of forcing a fresh rebalance.

The wrapper now refreshes historical `market_factors` across the requested window
from already-materialized `Source A` history, then builds missing CW2 month-end
snapshots.

```bash
team_Pearson/coursework_one/.venv/bin/python team_Pearson/coursework_two/scripts/backfill_monthly_snapshots.py \
  --start-date 2021-04-01 \
  --end-date 2026-04-20 \
  --company-limit 0 \
  --cw1-config team_Pearson/coursework_one/config/conf.yaml \
  --cw2-config team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml
```

## Step 2.5: Month-End Breadth Gate Before Backtest

Do **not** go straight from Step 2 into backtest. First verify that the historical month-end snapshot targets are actually present across the window:

```bash
docker exec postgres_db_cw psql -U postgres -d fift -c "
SELECT as_of_date, COUNT(*) AS n_targets
FROM systematic_equity.portfolio_target_positions
GROUP BY as_of_date
ORDER BY as_of_date;
"
```

Hard requirements for the formal run:

- no month-end inside the intended backtest window should be missing entirely
- no month-end should have `0` target rows
- the breadth should be consistent with the active CW2 configuration, allowing valid off-cycle `frequency_carry` months but not isolated sparse failures

If this gate fails, stop and fix coverage / quality / constraint issues before Step 3 or Step 4. Do not treat a sparse-snapshot run as a valid strategy backtest.

## Step 3: CW2 Operate Flow

After upstream data and CW2 feature tables exist, run the operated portfolio workflow:

```bash
team_Pearson/coursework_one/.venv/bin/python team_Pearson/coursework_two/Main.py \
  --mode operate \
  --run-date 2026-04-20 \
  --company-limit 0 \
  --cw1-config team_Pearson/coursework_one/config/conf.yaml \
  --cw2-config team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml
```

This writes:

- `portfolio_recommendations`
- `portfolio_recommendation_items`
- `portfolio_recommendation_decisions` when decision modes are used
- `portfolio_update_decisions`
- readiness/audit outputs

## Step 4: CW2 Backtest and Analysis

Run only after historical `portfolio_target_positions` are available for the window being tested and the Step 2.5 breadth gate passes.

```bash
team_Pearson/coursework_one/.venv/bin/python team_Pearson/coursework_two/Main.py \
  --mode backtest-and-analyse \
  --run-date 2026-04-20 \
  --run-name cw2_formal_20260420_fund_ra3_s30_t50 \
  --cw1-config team_Pearson/coursework_one/config/conf.yaml \
  --cw2-config team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml
```

If a report is needed from an existing `run_id`:

```bash
team_Pearson/coursework_one/.venv/bin/python team_Pearson/coursework_two/Main.py \
  --mode report \
  --run-id <BACKTEST_RUN_ID> \
  --report-name cw2_formal_fund_ra3_s30_t50_20260420_report \
  --cw1-config team_Pearson/coursework_one/config/conf.yaml \
  --cw2-config team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml
```

## Verification Queries

PostgreSQL row-count checks:

```bash
docker exec postgres_db_cw psql -U postgres -d fift -c "
SELECT 'factor_observations', COUNT(*) FROM systematic_equity.factor_observations
UNION ALL
SELECT 'financial_observations', COUNT(*) FROM systematic_equity.financial_observations
UNION ALL
SELECT 'benchmark_prices', COUNT(*) FROM systematic_equity.benchmark_prices
UNION ALL
SELECT 'feature_factor_scores', COUNT(*) FROM systematic_equity.feature_factor_scores
UNION ALL
SELECT 'portfolio_target_positions', COUNT(*) FROM systematic_equity.portfolio_target_positions;
"
```

PostgreSQL quality gate — any non-pass row means the run is not trustworthy even if row counts look reasonable:

```bash
docker exec postgres_db_cw psql -U postgres -d fift -c "
SELECT run_date, dataset_name, status
FROM systematic_equity.quality_snapshots
WHERE status != 'pass'
ORDER BY run_date DESC
LIMIT 50;
"
```

Per-as_of_date breadth check (catches the near-empty-portfolio failure mode where row counts are non-zero but most months have no targets):

```bash
docker exec postgres_db_cw psql -U postgres -d fift -c "
SELECT as_of_date, COUNT(*) AS n_targets
FROM systematic_equity.portfolio_target_positions
GROUP BY as_of_date
ORDER BY as_of_date;
"
```

Source B coverage contract check (formal run should not have unexpected missing symbols):

```bash
docker exec postgres_db_cw psql -U postgres -d fift -c "
SELECT source_name, status, COUNT(*) AS n_symbols
FROM systematic_equity.source_coverage_audit
WHERE run_date = '2026-04-20'
GROUP BY source_name, status
ORDER BY source_name, status;
"
```

If `source_b` shows `missing_or_failed` or any unexpected-missing class for the formal run, do not trust downstream sentiment-derived factor coverage even if Mongo contains documents.

Mongo quick check:

```bash
docker exec mongo_db_cw mongosh ift_cw --quiet --eval "db.news_articles.countDocuments()"
docker exec mongo_db_cw mongosh ift_cw --quiet --eval "db.news_articles.getIndexes().map(i => i.name)"
```

Mongo is necessary but not sufficient. Treat Mongo row counts only as one layer of the `Source B` acceptance criteria; the formal run is only acceptable when:

- MinIO raw history is present through `2026-02-28`
- incremental `2026-03-01` onward objects have been collected
- Mongo has indexed the combined history + increment
- PostgreSQL downstream coverage and quality gates also pass

Redis quick check (expect non-empty dedup set after incremental ingestion, and no stuck circuit breakers):

```bash
docker exec team_pearson_redis redis-cli DBSIZE
docker exec team_pearson_redis redis-cli --scan --pattern 'cw1:news:seen_urls*' | wc -l
docker exec team_pearson_redis redis-cli KEYS 'circuit_breaker:*'
```

## Notes on Reproducibility

- This process is **script-driven** and **database-backed**.
- `PostgreSQL` remains the curated system of record.
- `MinIO` holds raw/replay objects.
- `MongoDB` is the document store for `Source B` articles and is rebuildable from raw news.
- `Redis` holds runtime dedupe and resilience state.
- `Kafka` is optional event fan-out, not the primary truth store.

For the formal run, the accepted `Source B` state is:

- `MinIO`: complete canonical raw archive through `2026-02-28` plus incremental objects from `2026-03-01` onward
- `MongoDB`: complete `news_articles` corpus rebuilt from that raw store
- `PostgreSQL`: downstream sentiment-derived factor chain materialized and quality-checked across the full window

## Current Caveat

`CW2` full-history backtests require historical month-end `portfolio_target_positions` snapshots.

If those snapshots are not yet materialized across the whole window, first complete:

1. `CW1` full upstream load
2. `CW2` historical month-end snapshot / feature / portfolio generation

before treating the backtest as the final full-sample run.
