# Team Pearson — Coursework Two (CW2)

CW2 is the **alpha modelling, portfolio construction, backtesting, and reporting layer** of the Team Pearson institutional-grade quantitative equity platform. It is built directly on top of CW1's curated data warehouse, rather than duplicating ingestion code.

This README is the operating manual for CW2. For the project-level overview, headline results, and repository layout, see the [Team Pearson README](../README.md).

---

## 0. CW2 Directory Layout

```
team_Pearson/coursework_two/
|-- Main.py                       # CW2 CLI entrypoint (full-run / features / backtest / report / ...)
|-- Launch_CW2_Full_Workflow.cmd  # Windows one-command full workflow launcher
|-- Launch_CW2_Web.cmd            # Windows web launcher
|-- api/                          # FastAPI service for the connected dashboard/report studio
|-- web/                          # Browser UI assets and web documentation
|-- config/                       # Strategy configuration
|   |-- conf.yaml                 # Default config aligned with the formal baseline
|   |-- experiments/formal/       # Pinned formal reference configurations
|   |-- experiments/mini_sweep/   # Parameter-search candidates
|   `-- ablation/                 # Ablation and constrained-search variants
|-- inputs/                       # Minimal formal raw seed used by the web dashboard
|   `-- formal_slim_6905_20260420_extracted/
|-- modules/                      # Production Python packages
|   |-- feature/                  # Factor engine, preprocessing, composite alpha
|   |-- risk/                     # Risk overlay and covariance model
|   |-- portfolio/                # Universe screen and constrained optimiser
|   |-- backtest/                 # Execution, performance, and persistence
|   |-- analysis/                 # Benchmark, attribution, regime, and scorecard metrics
|   |-- reporting/                # Report package and chart generation
|   |-- robustness/               # Robustness-output persistence helpers
|   |-- recommendation/           # Portfolio recommendation publishing
|   |-- ops/                      # Audit, Kafka, monitoring, and runtime control
|   `-- utils/                    # Config contracts, validation, governance helpers
|-- scripts/                      # Full workflow, robustness, report, quality, and utility CLIs
|-- tests/                        # CW2 pytest suite (80% coverage gate)
|-- sql/                          # CW2 schema migrations
|-- outputs/                      # Checked-in formal evidence only, not a general data dump
|   |-- reports/                  # Formal report package and report index
|   |-- robustness/               # Formal robustness Part 1-Part 5 evidence pack
|   |-- web_state/                # Curated web/report-studio state used by the dashboard
|   |-- micro_alpha_sweeps/       # Parameter-selection evidence kept for traceability
|   `-- formal_sweeps/            # Formal selection rankings kept for traceability
|-- repro/                        # Frozen reproduction contract for the formal reference run
`-- docs/                         # CW2 runbooks, design notes, and full-workflow docs
```

Recommended starting points: read the formal config, the checked-in formal report, the robustness evidence pack, and the repro contract in that order to follow the strategy from definition to verification.

---

## 1. Strategy Overview

The formal CW2 strategy `cw2_formal_20260420_fund_ra3_s30_t50` is a quarterly-rebalanced long-only U.S. equity portfolio designed to deliver a superior **risk-adjusted return** versus a passive market benchmark, after realistic trading frictions.

### 1.1 Investment Universe

A 678-name U.S. equity universe sourced from CW1's curated equity master, screened on country, market cap, liquidity, and data quality. The screen runs at every rebalance date and is materialised in `feature_universe_screen`.

### 1.2 Five-Factor Cross-Sectional Alpha Model

Each top-level factor is composed of multiple sub-variables to avoid single-proxy bias:

| Factor | Sub-variables |
|---|---|
| Quality | EBITDA margin, ROE, debt-to-equity (inverted) |
| Value | Book-to-price, earnings-to-price, EBITDA-to-EV |
| Market / Technical | Momentum 1m, momentum 6m, momentum 12-1m |
| Sentiment | News sentiment 7d avg, 30d avg, surprise |
| Dividend | Dividend yield, dividend stability, payout sustainability |

Sub-variables are sector-neutralised, winsorised at the 2.5% level, and z-scored cross-sectionally before composition into a single per-name composite alpha (`feature_factor_scores.composite_alpha`).

### 1.3 VIX-Based Regime Switching

The composite alpha applies different factor weightings depending on the prevailing market regime, classified by a hysteresis filter on VIX level and term spread:

| Factor | Normal regime | Stress regime |
|---|---:|---:|
| Quality | 0.18 | 0.40 |
| Value | 0.24 | 0.10 |
| Market/Technical | 0.43 | 0.05 |
| Sentiment | 0.00 | 0.05 |
| Dividend | 0.15 | 0.40 |

Hysteresis (entry threshold ≠ exit threshold, plus persistence requirement) prevents whipsaw transitions during transient VIX spikes.

### 1.4 Mean-Variance Portfolio Construction

The composite alpha and the per-name covariance estimate are passed into a constrained mean-variance optimiser. The covariance model is a **fundamental-factor model** of the form Σ = X F Xᵀ + D, where:

- X contains style exposures (market beta, size, value, momentum, quality, volatility, liquidity, dividend) plus sector exposures
- F is the shrunk covariance of estimated factor returns
- D is diagonal specific risk with a configured floor

The optimiser maximises α − λ × variance subject to long-only, single-name (≤5%), sector (≤30%), and turnover (≤50%) constraints.

### 1.5 Parameter Selection

Construction parameters were not picked by hand. They were selected through a **Sharpe-ranked constrained search** over a discrete candidate grid (covariance method × risk aversion × sector cap × turnover cap), executed by `scripts/mini_target_sweep.py` and persisted under `outputs/micro_alpha_sweeps/20260429T021834Z/ranking.csv`. The selected configuration is:

| Parameter | Selected Value |
|---|---:|
| Covariance method | `fundamental_factor` |
| Risk aversion (λ) | 3.0 |
| Max sector weight | 0.30 |
| Turnover cap | 0.50 |
| Selection mode | hybrid (top 12% with min 25 / max 35 names) |
| Max single weight | 0.05 |
| Min target weight | 0.005 |

### 1.6 Execution Assumptions

Signals are generated on the rebalance reference date using point-in-time data (`publish_date ≤ decision_date`); trades execute at the adjusted close on T+1. Transaction cost is 15 bps per unit of weight traded, applied multiplicatively to the period return: r_net = (1 + r_gross) × (1 − c) − 1.

---

## 2. System Architecture

### 2.1 Operating Model

CW2 follows a **hybrid production-style architecture** with three temporal cadences:

- **Configured target generation** (quarterly by default): PIT-clean factor engineering, composite alpha, and target refresh.
- **Month-end snapshot layer**: monthly `portfolio_target_positions` rows act as audit / backtest anchors. Off-cycle months carry forward the previous target set when the active strategy refreshes less frequently than monthly.
- **Daily update decisions**: each trading day is classified as `monitor_only`, `risk_review`, or `full_rebalance`, so incremental data does not automatically trigger a full rebalance.

### 2.2 Storage Layer Responsibilities

| Layer | Stores |
|---|---|
| **PostgreSQL** (`systematic_equity` schema) | Canonical structured store for features, portfolio targets, backtest outputs, recommendations, and ops audit |
| **MinIO** | Raw provider payload archive (replay) + compressed covariance matrix snapshots referenced from `model_input_manifests` |
| **MongoDB** | Searchable news index used by the sentiment factor |
| **Redis** | Runtime state, Kafka consumer offsets, Airflow control-plane caches |
| **Kafka** (optional) | Event bus for `cw1.news.structured`, `cw2.risk.actions.*`, and `platform.runs.status` |

### 2.3 Source-A Provider Policy

CW2 inherits the CW1 multi-provider policy:

- **Market / price layer**: yfinance primary, Alpha Vantage fallback, EDGAR not used.
- **Financial layer**: yfinance scaffold, Alpha Vantage gap fill, EDGAR authoritative on overlapping core financial metrics.
- **Financial timing layer**: EDGAR filing date first, then provider date, then fallback.

### 2.4 Terminology Note

Three similarly named date fields appear across the platform and must be read distinctly:

- `CW1 as_of` — extraction/audit date on upstream curated rows.
- `CW2 as_of_date` — snapshot/decision date used by feature generation, portfolio construction, recommendations, and backtests.
- `CW2 signal_as_of_date` — signal anchor date used by the daily update-decision monitor; on non-trading days this may fall back to the latest eligible trading-day factor snapshot, even though the operational run still belongs to the calendar `run_date`.

These three fields are **not interchangeable join keys**.

---

## 3. Benchmark and Control Series

The strategy is evaluated against three deliberately distinct comparison series:

| Series | Role | Cost Treatment | Question Answered |
|---|---|---|---|
| `SPY` | Primary external benchmark | Buy-and-hold; no execution cost | Does the strategy beat passive U.S. large-cap exposure? |
| `universe_ew` | Secondary same-universe comparison | Gross of trading costs | Does the factor engine and dynamic optimisation add value beyond naïve equal-weight on the same opportunity set? |
| `static_baseline` | Construction-layer control | Net of 15 bps | What is the marginal value of optimisation and regime overlay over a tradable equal-weight implementation of the same factor stack? |

`universe_ew` is intentionally kept gross because it is an opportunity-set reference, not a tradable counterfactual; charging it a cost would conflate factor alpha with an asymmetric cost penalty. `static_baseline` is charged the same 15 bps as the strategy because it *is* a tradable counterfactual — fair comparison requires the same net-of-cost basis.

---

## 4. Cold Start On A New Machine

Use this when bootstrapping the repo from scratch.

### 4.1 Host prerequisites

- `git`
- Docker Desktop or Docker Engine with `docker compose`
- Python 3.11
- Poetry

### 4.2 Bootstrap

```bash
# 1. Clone and enter the repo
git clone <repo-url> && cd <repo-root>

# 2. Create the shared CW1 environment file from the template
cp team_Pearson/coursework_one/.env.example team_Pearson/coursework_one/.env

# 3. Optionally create a CW2-specific override
cp team_Pearson/coursework_two/.env.example team_Pearson/coursework_two/.env

# 4. Install shared Python dependencies once from CW1
cd team_Pearson/coursework_one && poetry install && cd ../..

# 5. Start shared infrastructure
docker compose \
  -f docker-compose.yml \
  -f team_Pearson/coursework_one/docker-compose.pearson.override.yml up -d \
  postgres_db mongo_db miniocw minio_client_cw team_pearson_redis kafka_cw airflow_cw cw2_kafka_audit_consumer

# 6. Load shared environment variables
set -a && source team_Pearson/coursework_one/.env && set +a

# 7. Run the one-command full workflow
team_Pearson/coursework_one/.venv/bin/python team_Pearson/coursework_two/Main.py \
  --mode full-run \
  --run-date 2026-04-20 \
  --cw2-config team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml
```

For the full workflow, the default route uses the full configured universe and
does not enable the runtime smoke profile. Developers may explicitly add
`--smoke-profile`, `--smoke-lookback-years N`, and optionally `--company-limit`
for faster local plumbing checks; any smoke-profile or capped run is not formal
performance evidence. The `--quick-profile` and `--quick-lookback-years` spellings
are accepted as aliases, but `--smoke-*` is the documented interface.

If `airflow_cw` cannot resolve `kafka_cw` / `miniocw` or reports `ModuleNotFoundError: kafka`, the container is stale. Rebuild and recreate:

```bash
docker compose \
  -f docker-compose.yml \
  -f team_Pearson/coursework_one/docker-compose.pearson.override.yml up -d --build --force-recreate \
  miniocw minio_client_cw team_pearson_redis kafka_cw airflow_cw cw2_kafka_audit_consumer
```

### 4.3 Minimal formal raw seed for the web dashboard

The GitHub submission includes a **minimal formal raw seed** at:

```text
team_Pearson/coursework_two/inputs/formal_slim_6905_20260420_extracted/
```

This seed is deliberately small. It contains the formal baseline run metadata
and the web-facing PostgreSQL CSV extracts needed by the dashboard:

- `backtest_performance`, `backtest_benchmark_nav`, and benchmark metrics
- `feature_factor_scores`, `feature_risk_overlay`, and universe/snapshot registries
- `backtest_holdings`, `backtest_trade_blotter`, and `backtest_execution_ledger`
- `backtest_factor_attribution`, covariance metrics, and covariance contributions
- portfolio targets, construction diagnostics, source coverage, and static company sectors

It intentionally excludes the large research warehouse tables such as
`factor_observations.csv.gz`, `feature_sub_scores.csv.gz`, and
`financial_observations.csv.gz`. The API lookup order is:

1. live local PostgreSQL / Docker Postgres, when available;
2. this minimal formal raw seed under `inputs/`;
3. checked-in robustness/report evidence for report-facing summaries.

This means a fresh clone can render the formal web dashboard from the included
seed, while a fully loaded local database still takes precedence when present.
The seed is tied to formal run id
`6905e84b-9e16-4106-8c0f-cd9ecce56728`, portfolio
`cw2_formal_20260420_fund_ra3_s30_t50`, and data cutoff `2026-04-20`.

### 4.4 Recurring setup

If the machine is already prepared, the minimum recurring setup is:

1. Start the shared infrastructure containers.
2. Ensure `team_Pearson/coursework_one/.env` is present and loaded.
3. Use the shared `team_Pearson/coursework_one/.venv` for all CW2 commands.

---

## 5. Reproducing the Formal Reference Run

The current pinned formal reference run is:

| Field | Value |
|---|---|
| Run id | `6905e84b-9e16-4106-8c0f-cd9ecce56728` |
| Run name | `cw2_formal_20260420_fund_ra3_s30_t50` |
| Config | [`config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml`](config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml) |
| Report | [`outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report.md`](outputs/reports/cw2_formal_fund_ra3_s30_t50_20260420_report/report.md) |
| Total return | 74.115402% |
| Annualised return | 11.939622% |
| Annualised volatility | 15.816019% |
| Sharpe ratio | 0.582195 |
| Max drawdown | 17.130802% |
| Information ratio vs SPY | 0.125923 |
| SPY total return | 67.755749% |

**Important**: `outputs/reports/` and `outputs/handoff/` are local generated paths, not the GitHub reproducibility contract. For an exact reproduction matching the checked-in formal metrics, use the frozen bundle workflow under [`repro/`](repro/):

- [`repro/README.md`](repro/README.md) — exact reproducibility contract
- [`repro/reference_run_20260420.json`](repro/reference_run_20260420.json) — pinned reference metrics
- [`repro/github_release_checklist_20260420.md`](repro/github_release_checklist_20260420.md) — release publishing checklist
- [`docs/full_run_repro.md`](docs/full_run_repro.md) — full-chain bootstrap and wiped-state rerun procedure

---

## 6. Operating Modes

`Main.py` is the CW2 entrypoint. It supports the following modes:

| Mode | Purpose |
|---|---|
| `full-run` | One-command full workflow wrapper: DB init → CW1 upstream → historical CW2 month-end snapshot backfill → readiness audit → CW2 operate → backtest → analyse → report |
| `features` | Build CW2 universe screen, factors, composite alpha, risk overlay, and portfolio targets from existing curated PostgreSQL data |
| `backtest` | Run the CW2 backtest engine from stored `portfolio_target_positions` |
| `analyse` | Run performance analysis from an existing `backtest_runs.run_id` |
| `backtest-and-analyse` | Run stored-strategy backtest and immediately write analysis outputs |
| `report` | Generate database-backed reporting package (charts + markdown + JSON) from an existing backtest run |
| `audit` | Read-only readiness audit across SQL, MinIO, MongoDB, Redis, and snapshot history |
| `monitor` | Persist and print the latest control-plane monitoring snapshot |
| `update-decision` | Materialise one rule-driven daily decision (`monitor_only` / `risk_review` / `full_rebalance` / `blocked`) |
| `operate` | Production-style flow: `features → recommendation → audit`, optionally with auto-approval/publication and a markdown briefing |
| `recommend` | Publish a formal portfolio recommendation object from latest `portfolio_target_positions` |
| `decide-recommendation` | Approve, reject, or publish an existing recommendation with an explicit audit trail |

The `--with-upstream` flag prepends a CW1 upstream pipeline refresh to any of the above.

### 6.1 One-command full chain

```bash
team_Pearson/coursework_one/.venv/bin/python team_Pearson/coursework_two/Main.py \
  --mode full-run \
  --run-date 2026-04-20 \
  --cw2-config team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml
```

For local debugging, `--company-limit` can cap the universe and
`--smoke-profile --smoke-lookback-years N` can request the relaxed runtime
smoke-validation profile, but the full workflow and formal evidence path should
omit those flags. Any capped or smoke-profile run validates plumbing only and
should not be interpreted as performance evidence. Debug runs may activate
feasibility fallback logic. The full workflow disables the Kafka event-audit
hard gate in its temporary config while separately checking Kafka socket
reachability.

Useful overrides:

```bash
  --backfill-years 5 \
  --transaction-cost-bps 15 \
  --report-name cw2_formal_fund_ra3_s30_t50_20260420_report
```

The wrapper prints a JSON summary with the historical snapshot window, each orchestration step status, the generated `backtest run_id`, and the final report artefact paths.

### 6.1.1 One-command full workflow: quality -> databases -> strategy -> robustness -> web

Use the full workflow command for the one-line end-to-end check. It validates
the CW2 quality gates, confirms the shared stores are reachable, checks Kafka
connectivity, runs the formal full-chain strategy/report path, refreshes
robustness evidence surfaces for the formal baseline, and verifies the web/API
endpoints that read those outputs.

From `team_Pearson/coursework_two`:

```bash
../.venv/Scripts/python.exe scripts/full_workflow.py --start-services --serve
```

On Windows the same flow can be launched with:

```text
Launch_CW2_Full_Workflow.cmd
```

The command prints the web URL and writes a machine-readable summary to
`outputs/web_state/full_workflow/latest.json`. It is the full workflow path; it
does not replace the formal baseline run `6905e84b-9e16-4106-8c0f-cd9ecce56728`
or the formal robustness evidence pack.

When the formal data and artifacts are already present, use the reuse mode to
test the full orchestration from infrastructure through robustness/web without
pulling data or rerunning the expensive full strategy chain:

```bash
../.venv/Scripts/python.exe scripts/full_workflow.py --start-services --reuse-existing-formal
```

`--reuse-existing-formal` verifies the pinned 6905 formal config, repro
contract, report package, robustness evidence, and web state before skipping the
full-chain stage. Robustness bridge and web endpoint checks still run unless
they are explicitly skipped.

### 6.2 Feature pipeline only

```bash
cd team_Pearson/coursework_two
../coursework_one/.venv/bin/python Main.py \
  --mode features \
  --run-date 2026-04-20 \
  --company-limit 70 \
  --cw2-config ./config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml
```

To refresh upstream first, append `--with-upstream`.

### 6.3 Backtest only

```bash
cd team_Pearson/coursework_two
../coursework_one/.venv/bin/python Main.py \
  --mode backtest \
  --run-name cw2_formal_20260420_fund_ra3_s30_t50_repro \
  --cw2-config ./config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml
```

### 6.4 Analysis only

```bash
cd team_Pearson/coursework_two
../coursework_one/.venv/bin/python Main.py --mode analyse --run-id <backtest_run_id>
```

If a separate 25 bps robustness run exists for scorecard criterion 4:

```bash
../coursework_one/.venv/bin/python Main.py \
  --mode analyse \
  --run-id <main_run_id> \
  --robustness-run-id <robustness_25bps_run_id>
```

### 6.5 Report only

```bash
cd team_Pearson/coursework_two
../coursework_one/.venv/bin/python Main.py \
  --mode report \
  --run-id 6905e84b-9e16-4106-8c0f-cd9ecce56728 \
  --report-name cw2_formal_fund_ra3_s30_t50_20260420_report \
  --cw2-config ./config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml
```

### 6.6 Backtest + Analysis combined

```bash
../coursework_one/.venv/bin/python Main.py \
  --mode backtest-and-analyse \
  --run-name cw2_formal_20260420_fund_ra3_s30_t50_repro \
  --cw2-config ./config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml
```

### 6.7 Operated production-style flow

```bash
../coursework_one/.venv/bin/python Main.py \
  --mode operate \
  --run-date 2026-04-20 \
  --recommendation-name cw2_core_equity_20260420_live_note \
  --auto-approve \
  --auto-publish
```

This refreshes features → publishes a recommendation → runs readiness audit → emits a markdown briefing in `outputs/briefings/`.

### 6.8 Daily update decision

```bash
../coursework_one/.venv/bin/python Main.py \
  --mode update-decision \
  --run-date 2026-04-20 \
  --cw2-config ./config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml
```

### 6.9 Approve / publish a recommendation

```bash
../coursework_one/.venv/bin/python Main.py \
  --mode decide-recommendation \
  --recommendation-name cw2_core_equity_live_note \
  --decision-type approve \
  --actor pm_reviewer \
  --notes "Approved after monthly review."
```

---

## 7. Airflow Orchestration

The production-style orchestration layer ships three DAGs:

| DAG | Schedule (UTC) | Purpose |
|---|---|---|
| `cw1_pipeline_and_docs` | `0 6 * * *` | Daily upstream pipeline → curated-data validation → CW2 update-decision → Sphinx build → cadence-gated CW2 operate execution |
| `cw2_monthly_snapshot_backfill` | `30 9 1 * *` | Monthly month-end `portfolio_target_positions` snapshot maintenance, including `market_factors` refresh and post-backfill readiness audit |
| `cw2_backtest_analysis_report` | `30 11 1 * *` | Monthly preflight audit → backtest → analyse → report → verify → Kafka audit |

Scheduler-facing wrappers:

- [`scripts/run_update_decision.py`](scripts/run_update_decision.py)
- [`scripts/run_operated_flow.py`](scripts/run_operated_flow.py)
- [`scripts/run_backtest_analysis_report.py`](scripts/run_backtest_analysis_report.py)
- [`scripts/backfill_monthly_snapshots.py`](scripts/backfill_monthly_snapshots.py)
- [`scripts/run_full_chain.py`](scripts/run_full_chain.py)

---

## 8. Configuration Ownership

| Path | Scope |
|---|---|
| [`coursework_one/config/conf.yaml`](../coursework_one/config/conf.yaml) | Shared infrastructure, extractors, universe source, benchmark plumbing |
| [`coursework_two/config/conf.yaml`](config/conf.yaml) | CW2 factor definitions, preprocessing, universe screen, risk overlay, portfolio construction (defaults aligned to the formal baseline) |
| [`coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml`](config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml) | Pinned April 2026 formal reference configuration |

---

## 9. Testing

CW2 uses the shared Team Pearson Python environment, plus CW2-local quality
configuration. Install the optional developer gate tools from
`requirements-dev.txt` when preparing a clean marking machine:

```bash
cd team_Pearson/coursework_two
../.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
```

The local checks used for the final handoff are:

```bash
../.venv/Scripts/python.exe -m black --check modules scripts tests api
../.venv/Scripts/python.exe -m isort --check-only modules scripts tests api
../.venv/Scripts/python.exe -m flake8 --jobs=1 modules scripts tests api web
../.venv/Scripts/python.exe -m bandit -c bandit.yaml -r modules api web -ll
../.venv/Scripts/python.exe scripts/check_large_files.py --max-mb 5
../.venv/Scripts/python.exe -m sphinx -W --keep-going -b html docs docs/_build/html
../.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests --cov=modules --cov-report=html
```

`mypy --strict --follow-imports=skip modules api` and `pylint modules api` are
available as manual gates in `.pre-commit-config.yaml`; they are not part of the
default full workflow command because the inherited codebase still has a
documented typing/style baseline.

The preferred entry point is the unified quality gate:

```bash
# from the repository root
team_Pearson/coursework_two/scripts/run_quality_checks.sh
```

This runs:

- `poetry check` for the shared CW1 Poetry project used by CW2
- `poetry run black --check --line-length 100` over CW2 `Main.py`, `modules/`, `scripts/`, and `tests/`
- `poetry run isort --check --profile black --line-length 100` over the same paths
- `poetry run flake8` over CW2 `Main.py`, `modules/`, and `scripts/`
- `poetry run bandit -r` over CW2 `modules/` and `scripts/`
- `poetry run pytest -c ../coursework_two/pytest.ini ../coursework_two/tests/`

To also generate an HTML coverage report:

```bash
team_Pearson/coursework_two/scripts/run_quality_checks.sh --html-coverage
```

The HTML report is written to `team_Pearson/coursework_two/htmlcov/`, which is
ignored by Git.

To include a Sphinx documentation build in the same gate:

```bash
team_Pearson/coursework_two/scripts/run_quality_checks.sh --docs
```

To run dependency vulnerability scanning as a separate security audit:

```bash
team_Pearson/coursework_two/scripts/run_quality_checks.sh --with-safety --skip-tests
```

Safety scans the full shared CW1 Poetry environment, including Airflow and
developer tooling dependencies, so it is intentionally opt-in rather than part
of the default full-workflow reproducibility gate.

For targeted debugging, run pytest directly from the shared CW1 Poetry project:

```bash
cd team_Pearson/coursework_one

# Run all CW2 tests
poetry run pytest -c ../coursework_two/pytest.ini ../coursework_two/tests/

# Run a single CW2 test file
poetry run pytest -c ../coursework_two/pytest.ini ../coursework_two/tests/test_backtest_engine.py -v
```

The CW2 [`pytest.ini`](pytest.ini) measures coverage across `Main.py`,
`modules/`, and production-facing `scripts/`, and enforces
`--cov-fail-under=80`, so the full-suite command fails if coverage drops below
80%. The coverage config intentionally omits development/offline utilities used
for parameter materialisation, sweep scoring, and CSV export, because they are
not part of the formal strategy runtime or full-workflow reproduction path.

---

## 10. Outputs

### 10.1 PostgreSQL tables (curated)

Feature layer:

- `feature_universe_screen`, `feature_sub_scores`, `feature_factor_scores`, `feature_risk_overlay`
- `feature_snapshot_registry`, `portfolio_snapshot_registry`, `model_input_manifests`

Portfolio layer:

- `portfolio_target_positions`, `portfolio_construction_diagnostics`
- `portfolio_recommendations`, `portfolio_recommendation_items`, `portfolio_recommendation_events`, `portfolio_recommendation_decisions`
- `portfolio_update_decisions`

Backtest layer:

- `backtest_runs`, `backtest_holdings`, `backtest_performance`, `backtest_metrics`
- `backtest_benchmark_nav`, `backtest_relative_metrics`, `backtest_regime_attribution`
- `backtest_covariance_metrics`, `backtest_covariance_contributions`, `backtest_scorecard`
- `backtest_execution_ledger`, `backtest_intraday_events`, `backtest_trade_blotter` (unified SQL view)
- `backtest_reports`, `backtest_report_artifacts`

Operations layer:

- `ops_pipeline_runs`, `ops_stage_runs`, `ops_event_log`
- `ops_kafka_consumer_ack`, `ops_kafka_dead_letter`, `ops_kafka_lag_snapshots`
- `ops_health_snapshots`, `quality_snapshots`

### 10.2 MinIO artefacts

Compressed covariance matrix snapshots under `artifacts/cw2/portfolio_construction/covariance/...`. Object path, checksum, and symbol order are referenced from the `portfolio_input` manifest in `model_input_manifests`.

### 10.3 Filesystem outputs

- `outputs/reports/<report_name>/` — generated charts, `report.md`, `report_summary.json`, `trade_blotter.csv`
- `outputs/briefings/` — markdown briefings from `--mode operate`
- `outputs/micro_alpha_sweeps/` and `outputs/formal_sweeps/` — parameter selection evidence

### 10.4 Ex-ante risk diagnostics

The analysis layer reuses the same fundamental-factor covariance model to produce explicit ex-ante diagnostics, written into `backtest_covariance_metrics` and `backtest_covariance_contributions`:

- `ex_ante_volatility_ann`
- `ex_ante_tracking_error_ann`
- `diversification_ratio`
- `effective_risk_bets`
- Asset-level and sector-level risk contributions

---

## 11. Documentation Map

Active documentation is split by responsibility:

| Surface | Location | Purpose |
|---|---|---|
| Operating manual (this file) | `team_Pearson/coursework_two/README.md` | Day-to-day commands and configuration |
| Runbooks and design notes | [`docs/`](docs/) | CW2-specific design decisions, full-run procedures, research-upgrade snapshots |
| Reproducibility contract | [`repro/`](repro/) | Exact latest-run frozen bundle workflow |
| CW2 local Sphinx docs | [`docs/index.rst`](docs/index.rst) | Installation, usage, architecture, robustness/web flow, full workflow, API reference, operations, and quality gates |
| Shared Sphinx site (CW1 + CW2 platform reference) | [`../coursework_one/docs/sphinx/source/`](../coursework_one/docs/sphinx/source/) | Architecture, API reference, marker quick guide |

### 11.1 Sphinx Documentation (Auto-Generated)

CW2 now keeps a local Sphinx project under `coursework_two/docs` for the
full-workflow runbooks and quality evidence. Build it from `coursework_two`
with:

```bash
../.venv/Scripts/python.exe -m sphinx -W --keep-going -b html docs docs/_build/html
```

The shared CW1 + CW2 platform surface is still built from `coursework_one`,
combining:

- Hand-written architecture and methodology pages in **MyST-flavoured Markdown** under [`../coursework_one/docs/sphinx/source/`](../coursework_one/docs/sphinx/source/)
- Auto-generated API reference for every CW1 and CW2 Python module via `sphinx.ext.autodoc` and `sphinx.ext.napoleon`
- Cross-linked source view via `sphinx.ext.viewcode`

#### Main CW2-related pages

| Page | Topic |
|---|---|
| `cw2_pipeline.md` | End-to-end CW2 pipeline architecture |
| `cw2_core_modules.md` | Core module responsibilities and call graph |
| `cw2_handoff.md` | Formal strategy handoff package layout |
| `cw2_reproduction.md` | Reproducibility procedures and contract |
| `backtest_reporting.md` | Backtest engine and report generation |
| `benchmark_methodology.md` | Benchmark and control series design rationale |
| `data_implementation.md` | PostgreSQL / MinIO / MongoDB / Redis storage layer |
| `orchestration_eventing.md` | Airflow DAGs and Kafka eventing |
| `module_reference.md` | Auto-generated API reference index |
| `marker_quick_guide.md` | Marker-facing quick reference |

#### Local build

The Sphinx project ships a build helper that handles cleaning, doctree management, and `.env` loading:

```bash
cd team_Pearson/coursework_one

# Full rebuild (clears previous build output first)
poetry run python scripts/build_sphinx_docs.py --clean

# Incremental build (faster, only rebuilds changed pages)
poetry run python scripts/build_sphinx_docs.py
```

After a successful build, the HTML entrypoint is:

```
team_Pearson/coursework_one/docs/sphinx/build/html/index.html
```

Alternative make-based invocation (equivalent output):

```bash
cd team_Pearson/coursework_one/docs/sphinx
poetry run make html
```

#### Automated build via Airflow

The Airflow DAG `cw1_pipeline_and_docs` includes a `build_sphinx_docs` task that runs `scripts/build_sphinx_docs.py --clean` daily at `06:00 UTC` after the upstream pipeline and curated-data validation steps complete. This guarantees the published documentation tracks the current code state without manual intervention.

#### Configuration

Sphinx configuration lives at [`../coursework_one/docs/sphinx/source/conf.py`](../coursework_one/docs/sphinx/source/conf.py) and is shared across CW1 and CW2. Heavy runtime dependencies (psycopg2, yfinance, kafka, sqlalchemy, etc.) are declared in `autodoc_mock_imports` so the docs build cleanly on any machine without the full infrastructure stack running.

---

## 12. Quick Reference for Marking / Demonstration

| Goal | Command |
|---|---|
| Only CW2 feature stage | `Main.py --mode features` |
| CW2 features with fresh upstream | `Main.py --mode features --with-upstream` |
| Full end-to-end refresh | `Main.py --mode full-run` |
| Stored-strategy backtest | `Main.py --mode backtest` |
| Post-backtest analysis | `Main.py --mode analyse --run-id <run_id>` |
| Backtest + analysis | `Main.py --mode backtest-and-analyse` |
| Current ops snapshot | `Main.py --mode monitor` |
| Formal recommendation object | `Main.py --mode recommend` |
| Approval / publication workflow | `Main.py --mode decide-recommendation` |

CW2 deliberately does not duplicate CW1 ingestion code. It sits on top of the same curated data platform.
