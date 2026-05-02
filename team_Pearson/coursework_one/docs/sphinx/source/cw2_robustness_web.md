# CW2 Robustness and Web Workbench

This page documents the robustness and browser-workbench parts of the Team
Pearson platform. These are CW2-owned surfaces, but they are included in the
shared Sphinx site so a marker can open one documentation homepage and see how
the final investment report evidence, robustness checks, and web UI fit
together.

## Formal Baseline Contract

The robustness workflow is anchored to the current formal CW2 baseline:

- formal config: `team_Pearson/coursework_two/config/experiments/formal/cw2_formal_20260420_fund_ra3_s30_t50.yaml`
- formal portfolio: `cw2_formal_20260420_fund_ra3_s30_t50`
- formal run id: `6905e84b-9e16-4106-8c0f-cd9ecce56728`
- final report primary benchmark: `SPY`
- supporting comparator: `universe_ew`

The strategy is not a monthly rebalance strategy. Target weights are generated
quarterly, actual rebalancing is quarterly with the configured execution lag,
and monthly rows are holding-period performance records used to measure NAV,
Sharpe, information ratio, turnover, drawdown, and regime behaviour.

## Robustness Part Map

The robustness suite is grouped as Part 1 to Part 5.

| Part | Purpose | Main scripts / evidence |
|---|---|---|
| Part 1 | Deterministic sensitivity, including transaction cost and selected factor-weight scenarios | `scripts/run_sensitivity_analysis.py`, `outputs/robustness/sensitivity`, `outputs/robustness/report_evidence` |
| Part 2 | Ablation of factors, construction choices, and optimizer mechanisms | `scripts/run_ablation_analysis.py`, `outputs/robustness/ablation` |
| Part 3 | Sub-period and normal/stress regime attribution using monthly holding-period records | `scripts/run_subperiod_analysis.py`, `outputs/robustness/subperiod` |
| Part 4 | Stochastic and neighbourhood robustness, including bootstrap/Monte Carlo style checks and factor-weight neighbourhoods | `scripts/run_stochastic_robustness.py`, `scripts/run_test11_factor_neighbourhood.py`, `outputs/robustness/test11_factor_neighbourhood` |
| Part 5 | Evidence packaging for the written report and web display | `scripts/build_robustness_requirement_report.py`, `scripts/build_report_evidence_pack.py`, `scripts/persist_robustness_outputs.py` |

Part 5 is the bridge from raw robustness outputs into marker-facing evidence:
it states the formal run id, benchmark convention, quarterly execution cadence,
monthly measurement convention, and excludes legacy 2026-04-24 report outputs.

## Web Workbench Role

The browser workbench is a control and review surface. It does not own portfolio
logic. Strategy, backtest, robustness, and report generation remain in Python
modules and scripts. The web layer calls the FastAPI backend, and the backend
normalizes local SQL rows, JSON summaries, report files, robustness artifacts,
and saved web state into API responses.

Important web/API routes include:

- `/` for the single-page browser workbench
- `/health` for service readiness
- `/api/summary` for formal run and dashboard cards
- `/api/runs/recent` for run history
- `/api/artifacts` for generated report and evidence artifacts
- `/api/robustness/dashboard` for robustness overview cards
- `/api/robustness/acceptance` for the acceptance matrix
- `/api/robustness/report-evidence` for report-facing robustness evidence
- `/api/workbench/context` for connected scenario/report context

The main web areas relevant to CW2 marking are:

- **Robustness Lab**: connected robustness cards and acceptance evidence
- **Performance Dashboard**: NAV, drawdown, turnover, benchmark, and report metrics
- **Risk Dashboard**: exposure, risk contribution, and attribution summaries
- **Artifacts**: generated files, evidence packs, charts, PDFs, DOCX, CSVs
- **Report Studio**: AI-assisted report drafting and export, using local evidence

## One-Command Full Workflow

From `team_Pearson/coursework_two`, the full workflow command is:

```powershell
../.venv/Scripts/python.exe scripts/full_workflow.py --start-services --serve
```

Functionally this command is intended to cover the full end-to-end path:

1. run the CW2 quality/docs gate;
2. start or reuse PostgreSQL, MongoDB, MinIO, Redis, and Kafka;
3. verify database connectivity and the `systematic_equity` schema;
4. run the formal full-chain strategy/report path from the formal config;
5. refresh/persist formal robustness evidence surfaces;
6. start or reuse the FastAPI web server;
7. check that the web endpoints can read the connected outputs.

The command is not a separate temporary shortcut implementation. It demonstrates
that the same code paths used by the formal
portfolio, robustness evidence, and web workbench are wired together.

Optional developer-only flags such as `--smoke-profile`,
`--smoke-lookback-years N`, and `--company-limit` remain available for faster
plumbing checks. They are deliberately off by default and should not be used as
formal performance evidence. The `--quick-*` spellings remain accepted as
aliases, but the documented interface uses `--smoke-*`.

## Build and Open the Sphinx Site

From `team_Pearson/coursework_one`, rebuild the shared documentation site with:

```bash
poetry run python scripts/build_sphinx_docs.py --clean
```

The generated homepage is:

```text
team_Pearson/coursework_one/docs/sphinx/build/html/index.html
```

The navigation panel should include this page as **CW2 Robustness and Web
Workbench** alongside the existing architecture, usage, API, and reproduction
pages.
