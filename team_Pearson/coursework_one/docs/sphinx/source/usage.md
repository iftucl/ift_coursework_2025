# Usage Instructions

## Quick Start

Run from project root:

```bash
cd /Users/celiawong/Desktop/ift_coursework_2025/team_Pearson/coursework_one
```

### Standard daily run

```bash
poetry run python Main.py --run-date 2026-02-14 --frequency daily
```

### Teacher-style small sample acceptance run

```bash
poetry run python scripts/run_pipeline_and_index.py \
  --run-date 2026-02-14 \
  --frequency daily \
  --backfill-years 1 \
  --company-limit 5
```

Notes:
- `source_b` is enabled by default via `pipeline.enabled_extractors` (`source_a,source_b`).
- Mongo indexing is enabled by default in `run_pipeline_and_index.py` and `run_scheduled_pipeline.py`.
- Disable Mongo indexing explicitly with `--no-index-mongo` when needed.

## Command Reference

### Pipeline execution

| Goal | Command |
| --- | --- |
| Main pipeline single run | `poetry run python Main.py --run-date 2026-02-14 --frequency daily` |
| Run with scheduler wrapper (daily default) | `poetry run python scripts/run_scheduled_pipeline.py` |
| Weekly replay plan only | `poetry run python scripts/run_scheduled_pipeline.py --run-date 2026-03-02 --only weekly --plan-only` |
| Multi-frequency replay plan only | `poetry run python scripts/run_scheduled_pipeline.py --run-date 2026-04-01 --only daily,weekly,monthly,quarterly --plan-only` |

### Validation and inspection

| Goal | Command |
| --- | --- |
| Validate pipeline consistency | `poetry run python scripts/validate_pipeline_data.py --tolerance 1e-6` |
| Search Mongo news index | `poetry run python scripts/search_news.py --ticker AAPL --limit 10` |

### Quality and security gates

```bash
poetry run pytest -q
poetry run bandit -r modules Main.py scripts
VENV_PATH=$(poetry env info -p) && HOME=/tmp "$VENV_PATH/bin/safety" check -r poetry.lock
```

## Typical Run Sequence

1. Run `scripts/init_db.py` once on a fresh database.
2. Run `Main.py` or `run_pipeline_and_index.py` for ingestion and load.
3. Run `validate_pipeline_data.py` to confirm cross-source consistency.
4. Run `search_news.py` when checking indexed news retrieval behavior.

## Output Footprint

After a successful run, you should see:

- MinIO raw objects under `raw/source_a/...` and `raw/source_b/...`
- PostgreSQL updates in `factor_observations`, `financial_observations`, and `pipeline_runs`
- MongoDB documents in `ift_cw.news_articles`
- Optional quality snapshots in `systematic_equity.quality_snapshots`
