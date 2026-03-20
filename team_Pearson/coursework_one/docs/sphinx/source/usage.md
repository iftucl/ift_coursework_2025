# Usage Instructions

## 1. Quick Start

Run from project root:

```bash
cd team_Pearson/coursework_one
```

### 1.1 Standard daily run

```bash
poetry run python Main.py --run-date 2026-02-14 --frequency daily
```

### 1.2 Small-Sample Acceptance Run

```bash
poetry run python scripts/run_pipeline_and_index.py \
  --run-date 2026-02-14 \
  --frequency daily \
  --backfill-years 1 \
  --company-limit 5
```

Notes:
- `source_b` is enabled by default via `pipeline.enabled_extractors` (`source_a,source_b`).
- Mongo indexing is enabled by default in `Main.py`, `run_pipeline_and_index.py`, and `run_scheduled_pipeline.py`.
- Disable Mongo indexing explicitly with `--no-index-mongo` when needed.

## 2. Command Reference

### 2.1 Pipeline execution

| Goal | Command |
| --- | --- |
| Main pipeline single run | `poetry run python Main.py --run-date 2026-02-14 --frequency daily` |
| Main pipeline without Mongo indexing | `poetry run python Main.py --run-date 2026-02-14 --frequency daily --no-index-mongo` |
| Run with scheduler wrapper (daily default) | `poetry run python scripts/run_scheduled_pipeline.py` |
| Weekly replay plan only | `poetry run python scripts/run_scheduled_pipeline.py --run-date 2026-03-02 --only weekly --plan-only` |
| Multi-frequency replay plan only | `poetry run python scripts/run_scheduled_pipeline.py --run-date 2026-04-01 --only daily,weekly,monthly,quarterly --plan-only` |

### 2.2 Validation and inspection

| Goal | Command |
| --- | --- |
| Validate pipeline consistency | `poetry run python scripts/validate_pipeline_data.py --tolerance 1e-6` |
| Search Mongo news index | `poetry run python scripts/search_news.py --symbol AAPL --limit 10` |

### 2.3 Quality and security checks

```bash
poetry run pytest -q
poetry run bandit -r modules Main.py scripts
poetry run safety scan -r poetry.lock
```

If `safety scan` is run for the first time, authenticate once:

```bash
poetry run safety auth login --headless
```

## 3. Typical Run Sequence

<div>（1）On a freshly initialized environment, complete the Installation Guide first.</div>
<div>（2）Run <code>Main.py</code> or <code>run_pipeline_and_index.py</code> for ingestion and load.</div>
<div>（3）Run <code>validate_pipeline_data.py</code> to confirm cross-source consistency.</div>
<div>（4）Run <code>search_news.py</code> when checking indexed news retrieval behavior.</div>

## 4. Output Footprint

After a successful run, you should see:

- MinIO raw objects under `raw/source_a/...` and `raw/source_b/...`
- PostgreSQL updates in `factor_observations`, `financial_observations`, and `pipeline_runs`
- MongoDB documents in `ift_cw.news_articles`
- Optional quality snapshots in `systematic_equity.quality_snapshots`
