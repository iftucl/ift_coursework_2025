# UCL IFT — Big Data in Quantitative Finance Coursework 2025-26

This repository contains the Team Pearson submission for the UCL IFT module *Big Data in Quantitative Finance* (2025-26). The deliverable is a fully integrated, end-to-end, institutional-grade quantitative equity research platform spanning two coursework stages:

- **Coursework One (CW1)** — production data ingestion, curation, and storage layer
- **Coursework Two (CW2)** — alpha modelling, portfolio construction, backtesting, and reporting layer built directly on top of CW1

## Project Summary

Team Pearson delivers `cw2_formal_20260420_fund_ra3_s30_t50`, a quarterly-rebalanced long-only systematic U.S. equity strategy targeting **superior risk-adjusted return** relative to a passive market benchmark, while keeping drawdown and turnover under realistic implementation constraints.

The strategy combines:

1. A **five-factor cross-sectional alpha model** (quality, value, market/technical, sentiment, dividend), each composed of multiple sub-variables to avoid single-proxy bias.
2. A **VIX-based regime-switching mechanism** that dynamically tilts factor weights between *normal* and *stress* environments using hysteresis logic.
3. A **mean-variance portfolio optimiser** with a **fundamental-factor covariance model** (style + sector exposures with shrinkage), subject to long-only, single-name, sector, and turnover constraints.
4. A **Sharpe-ranked constrained parameter search** over the construction grid, yielding `risk_aversion=3.0` and `max_sector_weight=0.30` as the empirically optimal configuration.

## Headline Results (2021-04-20 to 2026-04-20, net of 15 bps trading cost)

| Metric | Strategy | SPY |
|---|---:|---:|
| Total return | **74.12%** | 67.76% |
| Annualised return | **11.94%** | 11.10% |
| Annualised volatility | 15.82% | 14.61% |
| Sharpe ratio | **0.582** | 0.568 |
| Maximum drawdown | **17.13%** | 22.37% |
| Information ratio vs SPY | 0.126 | — |
| Down-capture vs SPY | 0.882 | — |

Formal run id: `6905e84b-9e16-4106-8c0f-cd9ecce56728`. Pinned configuration: [`coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml`](coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml). Full report: [`coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report.md`](coursework_two/outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report.md).

## Benchmark Architecture

Three comparison series are constructed with deliberately different analytical roles:

| Series | Role | Cost Treatment | Question Answered |
|---|---|---|---|
| `SPY` | Primary external benchmark | Buy-and-hold; no execution cost | Does the strategy beat passive U.S. large-cap exposure? |
| `universe_ew` | Secondary same-universe comparison | Gross of trading costs | Does the factor engine and dynamic optimisation add value beyond naïve equal-weight? |
| `static_baseline` | Construction-layer control | Net of 15 bps | What is the marginal value of optimisation and regime overlay over a tradable equal-weight implementation of the same factor stack? |

`universe_ew` is intentionally kept gross: it is an opportunity-set reference, not a tradable counterfactual, so applying a cost model to it would conflate factor alpha with an asymmetric cost penalty. `static_baseline` is charged the same 15 bps as the strategy because it *is* a tradable counterfactual — the comparison only becomes fair on a net-of-cost basis.

## Repository Layout

```
team_Pearson/
|-- README.md                       # project entry point, headline results, architecture
|-- START_HERE_DELIVERY_BUNDLE.md   # delivery bundle entry point
|-- REFERENCE_STRATEGY_SUMMARY.md   # current formal strategy summary
|-- DATA_DELIVERY_SUMMARY.md        # data package delivery summary
|-- assets/README/                  # README images kept inside the team folder
|-- coursework_one/                 # CW1: ingestion, curation, storage
|   |-- Main.py                     # CW1 CLI entrypoint
|   |-- pyproject.toml              # shared Poetry project used by CW1 and CW2
|   |-- docker-compose.pearson.override.yml
|   |-- config/                     # extractor providers and shared infra config
|   |-- modules/                    # extract / transform / load / utils
|   |-- airflow/dags/               # orchestration DAGs
|   |-- scripts/                    # Sphinx build, healthchecks, helper scripts
|   |-- docs/sphinx/                # shared CW1+CW2 Sphinx documentation source
|   `-- tests/                      # CW1 pytest suite
`-- coursework_two/                 # CW2: alpha, portfolio, backtest, reporting, web
    |-- Main.py                     # CW2 CLI entrypoint
    |-- Launch_CW2_Full_Workflow.cmd
    |-- Launch_CW2_Web.cmd
    |-- api/                        # FastAPI dashboard/report API
    |-- web/                        # browser UI and web docs
    |-- config/                     # formal, sweep, and ablation configurations
    |-- modules/                    # feature, risk, portfolio, backtest, analysis, reporting, robustness
    |-- scripts/                    # full workflow, robustness, report, quality, utility CLIs
    |-- tests/                      # CW2 pytest suite with an 80% coverage gate
    |-- outputs/                    # checked-in formal reports, robustness evidence, and curated web state
    |-- repro/                      # frozen reproduction contract for the formal reference run
    `-- docs/                       # CW2 runbooks and design notes
```

Recommended starting points: `coursework_two/config/experiments/formal/`, `coursework_two/outputs/reports/`, `coursework_two/outputs/robustness/report_evidence/`, and `coursework_two/repro/`.

The repository-root `docker-compose.yml` is intentionally left as the upstream
coursework file. Team Pearson service additions and overrides live in
[`coursework_one/docker-compose.pearson.override.yml`](coursework_one/docker-compose.pearson.override.yml);
see [`coursework_one/docs/docker_compose_override.md`](coursework_one/docs/docker_compose_override.md).

## Data and Storage Architecture

The platform follows a layered data architecture with each storage layer assigned a single responsibility:

```
   ┌───────────────────────────────────────────────────────────────┐
   │  Source A (yfinance) │ Source B (Alpha Vantage) │ EDGAR        │
   └───────────────────────────────────────────────────────────────┘
                          │ CW1 ingestion
                          ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  MinIO  : raw provider payloads (replay archive)              │
   │  MongoDB: news index for sentiment factor lookups             │
   └───────────────────────────────────────────────────────────────┘
                          │ CW1 curation (PIT-clean)
                          ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  PostgreSQL: factor_observations, benchmark_prices,           │
   │              financial_observations, company_static, …        │
   └───────────────────────────────────────────────────────────────┘
                          │ CW2 feature engineering
                          ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  PostgreSQL: feature_universe_screen, feature_sub_scores,     │
   │              feature_factor_scores, feature_risk_overlay      │
   └───────────────────────────────────────────────────────────────┘
                          │ CW2 portfolio construction
                          ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  PostgreSQL: portfolio_target_positions, diagnostics, …       │
   │  MinIO     : compressed covariance matrix snapshots            │
   └───────────────────────────────────────────────────────────────┘
                          │ CW2 backtest + analysis + reporting
                          ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  PostgreSQL: backtest_runs, backtest_performance,             │
   │              backtest_metrics, backtest_relative_metrics,     │
   │              backtest_regime_attribution, backtest_scorecard, │
   │              backtest_reports, backtest_trade_blotter         │
   │  Filesystem: outputs/reports/<name>/report.md + charts        │
   │  Redis     : runtime state + Kafka audit cursor               │
   │  Kafka     : risk action + run-status event bus (optional)    │
   └───────────────────────────────────────────────────────────────┘
```

Storage role summary:

- **PostgreSQL (`systematic_equity` schema)** — canonical structured store for every materialised stage: factors, portfolio targets, backtest performance, analysis metrics, recommendations, and operational audit tables.
- **MinIO** — raw provider payload archive (replay) and large covariance matrix snapshots.
- **MongoDB** — searchable news index used by the sentiment factor.
- **Redis** — runtime state, Kafka consumer offsets, and Airflow control-plane caches.
- **Kafka (optional)** — event bus for `cw1.news.structured`, `cw2.risk.actions`, and `platform.runs.status` topics. SQL and MinIO remain the canonical stores; Kafka is used only for low-latency fan-out.

## Quick Start

For full setup, operating modes, and testing, see [`coursework_two/README.md`](coursework_two/README.md). The shortest reproducible path on a clean machine:

```bash
# 1. clone, install, and start infrastructure
git clone <repo-url> && cd <repo-root>
cp team_Pearson/coursework_one/.env.example team_Pearson/coursework_one/.env
cd team_Pearson/coursework_one && poetry install && cd ../..
docker compose -f docker-compose.yml \
  -f team_Pearson/coursework_one/docker-compose.pearson.override.yml up -d \
  postgres_db mongo_db miniocw minio_client_cw team_pearson_redis kafka_cw airflow_cw

# 2. load shared environment
set -a && source team_Pearson/coursework_one/.env && set +a

# 3. run the one-command full workflow
team_Pearson/coursework_one/.venv/bin/python team_Pearson/coursework_two/Main.py \
  --mode full-run \
  --run-date 2026-04-20 \
  --cw2-config team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml
```

For quicker end-to-end validation on a small sample, use the same entrypoint
with the smoke profile enabled:

```bash
team_Pearson/coursework_one/.venv/bin/python team_Pearson/coursework_two/Main.py \
  --mode full-run \
  --run-date 2026-04-20 \
  --company-limit 8 \
  --smoke-profile \
  --smoke-lookback-years 1 \
  --cw1-config team_Pearson/coursework_one/config/conf.yaml \
  --cw2-config team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml
```

The smoke profile validates the full CW1 -> CW2 -> backtest -> analysis ->
report path quickly. It is not the formal performance run; small-universe
feasibility fallbacks can be triggered by design. The older `--quick-*` option
names are still accepted as aliases.

For an exact reproduction matching the checked-in formal reference metrics, use the frozen reproduction contract under [`coursework_two/repro/`](coursework_two/repro/).

## CW2 Quality Gate

The CW2 build/check entrypoint is:

```bash
team_Pearson/coursework_two/scripts/run_quality_checks.sh
```

It runs the CW2 checks through the shared CW1 Poetry environment: `poetry
check`, `black --line-length 100`, `isort --profile black --line-length 100`,
`flake8`, `bandit`, and `pytest` with the checked-in CW2 coverage configuration.
Add `--docs` to include the shared Sphinx documentation build,
`--html-coverage` to write `team_Pearson/coursework_two/htmlcov/`, or
`--with-safety --skip-tests` for a separate dependency vulnerability audit of
the full shared Poetry environment.

## Documentation

The platform ships a **shared CW1 + CW2 Sphinx documentation site** that is rebuilt automatically by the Airflow `cw1_pipeline_and_docs` DAG every day. The Sphinx site combines hand-written architecture notes (MyST-flavoured Markdown) with `autodoc`-generated API reference for every CW1 and CW2 Python module.

To build the docs locally:

```bash
cd team_Pearson/coursework_one
poetry run python scripts/build_sphinx_docs.py --clean
# HTML entrypoint: team_Pearson/coursework_one/docs/sphinx/build/html/index.html
```

Key reference points:

- **Operating manual**: [`coursework_two/README.md`](coursework_two/README.md)
- **CW1 ingestion guide**: [`coursework_one/README.md`](coursework_one/README.md)
- **Reproducibility contract**: [`coursework_two/repro/README.md`](coursework_two/repro/README.md)
- **Full-chain runbook**: [`coursework_two/docs/full_run_repro.md`](coursework_two/docs/full_run_repro.md)
- **Sphinx site source** (CW1 + CW2 platform reference): [`coursework_one/docs/sphinx/source/`](coursework_one/docs/sphinx/source/)
- **Sphinx build script**: [`coursework_one/scripts/build_sphinx_docs.py`](coursework_one/scripts/build_sphinx_docs.py)

## Coursework Teams

| Team | Name |
|------|------|
| 0 | Bernoulli |
| 1 | Kolmogorov |
| 2 | Neyman |
| 3 | Luzin |
| 4 | **Pearson** |
| 5 | Russell |
| 6 | Wittgenstein |
| 7 | Wald |
