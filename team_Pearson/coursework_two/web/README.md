# CW2 Web Platform

## Purpose

This directory contains the browser-based control and reporting surface for the
CW2 formal S30 portfolio workflow. The page is served by the FastAPI backend and
is intended to help reviewers inspect the strategy, connected outputs,
robustness evidence, and AI-assisted report generation flow from one place.

The web app reflects the formal quarterly-rebalanced baseline: target weights
are generated quarterly, actual rebalancing is quarterly with execution lag, and
monthly rows are used for performance measurement, monitoring, drawdown, IR,
Sharpe, and turnover records. Monthly monitoring and snapshot tools are present,
but they do not imply monthly portfolio re-optimisation.

## Included pages

- `Welcome`
- `System Overview`
- `Scenario Builder`
- `Universe & Company Selector`
- `Regime & Threshold Control`
- `Portfolio Optimizer Settings`
- `Data Health`
- `Backtest Runner`
- `Run History`
- `Factor Lab`
- `Performance Dashboard`
- `Risk Dashboard`
- `Robustness Lab`
- `Trade Blotter & Execution`
- `Artifacts`
- `Report Studio`
- `Help`

## Current state

- `index.html` defines the single-page app container.
- `styles.css` defines the visual system, cards, modals, grids, and responsive
  behaviour.
- `main.js` renders page content, navigation, connected cards, modal editing,
  model-provider controls, and API calls.
- `e2e/cw2_smoke.spec.js` contains the Playwright smoke flow for the connected
  browser workbench.
- `../api/main.py` serves the web assets and exposes the local `/api/...`
  routes used by the browser.

The preferred mode is connected API mode. Static text and empty states remain so
the browser can explain missing artifacts cleanly, but the main performance,
risk, run-history, artifact, robustness, and report-studio views are wired to
real local data surfaces.

## Connected data

The web layer reads from these project-owned surfaces when they are available:

- `inputs/formal_slim_6905_20260420_extracted/formal_slim_6905_20260420`
- `outputs/robustness/report_evidence`
- `outputs/robustness/requirement_report`
- `outputs/robustness/subperiod`
- `outputs/robustness/test11_factor_neighbourhood`
- `outputs/web_state`

The formal slim package is the source for the current baseline metadata,
portfolio/backtest artifacts, benchmark context, attribution evidence, and
connected dashboard summaries. `outputs/web_state` stores browser-side workflow
state such as saved scenarios, audit logs, report history, and local LLM session
settings.

The slim package is checked into Git only to support reproducible web operation:
without it, a fresh clone can start the UI but cannot populate the real
performance, holdings, attribution, artifact, and report-generation surfaces
unless the reviewer also imports the full local database. Large warehouse tables
remain excluded.

Scenario preview cards and some risk lenses are derived UI views over the formal
configuration and output context. AI report generation requires a user-supplied
API key in the local session; saved API keys are hidden by design.

## How to open

Open `index.html` directly only for a limited static preview. Connected cards,
report generation, model discovery, run history, artifact previews, and
robustness summaries require the local API server.

If local script loading is blocked by the browser, use a simple local static
server instead of `file://`.

## How to run with the API

The preferred mode is to serve the web shell through the CW2 API so the page
can call relative `/api/...` routes without cross-origin setup.

### One-command full workflow

For the full end-to-end workflow, run this from `team_Pearson/coursework_two`:

```bash
../.venv/Scripts/python.exe scripts/full_workflow.py --start-services --serve
```

This command starts the shared stores if requested, checks the quality/docs gate,
runs the formal full-chain strategy/report path, refreshes robustness evidence
for the formal baseline, verifies the web API endpoints, and leaves the browser
server open at `http://127.0.0.1:8011/`.

By default it runs the full workflow path. `--smoke-profile`,
`--smoke-lookback-years N`, and `--company-limit` remain available for developer
plumbing checks, but those optional flags should not be used as formal report
evidence. `--quick-profile` and `--quick-lookback-years` are accepted aliases.

### Double-click launch on Windows

If you do not want to type commands, use either of these launchers from the
`coursework_two` folder:

- `Launch_CW2_Web.cmd`
- `Launch_CW2_Web_Silent.vbs`
- `Launch_CW2_Full_Workflow.cmd` for the full workflow chain

Both files:

- start the local FastAPI server
- wait until the server is ready
- open the browser automatically at `http://127.0.0.1:8011/`

The `.vbs` version hides the terminal window and is the closest option to a
"double-click app" launcher on Windows.

### Manual launch

From `team_Pearson/coursework_two`, run:

```bash
uvicorn api.main:app --host 127.0.0.1 --port 8011
```

Then open:

- `http://127.0.0.1:8011/`
- `http://127.0.0.1:8011/api/summary`

## Quality notes

The browser button sweep evidence is stored at:

- `outputs/web_state/button_test_logs/button_sweep_final_result.json`

The current sweep records 213 safe button interactions with zero failures. Rerun
the browser sweep after UI changes that add or rename buttons, modals, or page
navigation targets.

## Maintenance targets

1. Refresh the formal slim input bundle and robustness outputs when the formal
   run id changes.
2. Re-run the browser smoke sweep after frontend edits.
3. Keep Report Studio text-based PDF and DOCX export behaviour aligned with the
   final report format.
4. Keep the dev quality commands documented in the project requirement checklist
   runnable from a clean local virtual environment.
