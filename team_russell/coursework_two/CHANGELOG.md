# Changelog — Team RUSSEL CW2 Pipeline

All notable changes to the CW2 pipeline are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

---

## [0.5.2] — 2026-05-01

### Fixed
- `main.py`: commented out step 02 from the default pipeline — it requires
  PostgreSQL which reviewers won't have; pre-built `stock_returns_10year.csv`
  is included so steps 03–09 run without any database.
- `README.md`: added prominent note that no database or WRDS credentials are
  needed; clarified that `poetry install` is required before first run;
  moved PostgreSQL/WRDS into an optional "reproduce from raw data" block.

---

## [0.5.1] — 2026-05-01

### Fixed
- `dashboard/app.py`: removed unused `mean_rf_annual` import (F401).
- `scripts/step01_wrds_pull.py`: removed unused `os` import (F401); converted two
  bare f-strings (no placeholders) to plain strings (F541).
- `.flake8`: added `scripts/test_sw_full_analysis.py` and `scripts/test_score_weighting.py`
  to `exclude` list (exploratory scripts, not part of the submission pipeline).

### Changed
- `black --line-length 100` and `isort` applied to `main.py`, `api/queries.py`,
  `dashboard/app.py`, and `scripts/step01_wrds_pull.py` — zero flake8 violations
  across all pipeline and API/dashboard files.

---

## [0.5.0] — 2026-04-28

### Fixed
- `api/queries.py`: `get_quintile_summary()` now computes Sharpe and Sortino in
  Python using `rf_quarterly_series()` (time-varying per-period Rf) instead of
  the incorrect SQL formula `(ann_return − mean_rf) / ann_vol`; displayed Sharpe
  was 0.699 vs correct 0.660.
- `api/queries.py`: `RISK_FREE_ANNUAL` now sourced from `mean_rf_annual()` rather
  than hardcoded `0.0214`.
- `api/queries.py`: model string corrected from `40%+40%+20%` to `35%+35%+30%`.
- `api/queries.py`: `get_stocks_by_date_quintile()` now returns `momentum_score`.
- `dashboard/app.py`: sidebar factor weights corrected to `35% · 35% · 30%`.
- `dashboard/app.py`: benchmark error message corrected to `step06_benchmark.py`.
- `dashboard/app.py`: Overview KPI card relabelled from "IC Hit Rate" to
  "Q1 Hit Rate" (was showing Q1 portfolio hit rate, not IC hit rate).
- `dashboard/app.py`: benchmark KPI row Sharpe now uses `rf_quarterly_series()`
  per quarter instead of fixed `mean_rf_annual()`.
- `dashboard/app.py`: Stock Browser now displays `Momentum` score column.
- `dashboard/app.py`: quintile and IC table row highlight colours replaced with
  dark-mode-compatible tints (`#1c3d5a` / `#5c2010`) — pastel colours were
  unreadable against white text in Streamlit dark theme.

### Added
- `api/queries.py`: `get_quintile_summary()` now also returns `sortino_ratio`
  per quintile.
- `dashboard/app.py`: Performance page quintile table now shows Sortino Ratio column.

---

## [0.4.0] — 2026-04-27

### Added
- `scripts/_rf_rates.py`: lookup table of FRED DGS3MO 3-month T-bill rates for all
  40 quarterly holding periods (Dec 2015 – Sep 2025). Exports `get_rf_annual()`,
  `get_rf_quarterly()`, `rf_quarterly_series()`, and `mean_rf_annual()`.
- `tests/test_rf_rates.py`: 26 new tests covering all four exported functions —
  known-date lookup, near-zero/high-rate eras, fallback behaviour, pd.Index/
  pd.Series/list input forms, and index preservation (244 tests total).
- `step07_final_charts.py`: `compute_annual_returns()` and `chart_annual_returns_table()`
  generate a styled PNG table (`07c_q1_annual_returns_table.png`) showing compounded
  annual Q1 gross/net returns vs EW Universe for each calendar year 2016–2025,
  with colour-coded ▲/▼ benchmark beat flag and FAIL-row amber highlight.
- `tests/test_step07_charts.py`: 14 new tests for `compute_annual_returns`.
- `main.py` and `README.md` updated to register `07c_q1_annual_returns_table.png`.

### Changed
- **Risk-free rate**: replaced fixed `RISK_FREE_ANNUAL = 0.0214` constant with
  period-specific 3mo T-bill rates from `_rf_rates.py` across all six pipeline
  scripts (step02/03/05/06/08/09). Sharpe and Sortino are now computed as
  `ann_excess / ann_vol` where `excess_q = r_q − rf_q(date)` per quarter.
- `ann_stats(series, rf_q)` in step06/step09 and `jensen_alpha(port, bm, rf_q)`
  in step06 now require `rf_q: pd.Series` — no silent fallback to a fixed rate.
- Sortino downside threshold changed from 0 to period-specific Rf (excess returns
  below Rf count as downside), consistent with the Sharpe formulation.
- Chart and table titles updated from "Rf = 2.14% p.a." to "Rf = 3mo T-bill".
- `docs/` added to `.gitignore`; `CW2_Report_Draft.md` untracked from git.

### Fixed
- `compute_annual_returns()` now returns an empty DataFrame with correct column
  schema (instead of raising `KeyError: 'year'`) when no qualifying rows exist.

### Results impact
- Q1 Sharpe: 0.701 → **0.660** (high-rate 2023–2024 periods now correctly penalised)
- Q1 Sortino: 1.104 → **1.011** (downside now measured vs Rf, not vs zero)
- Buffer-zone Sharpe: 0.703 → **0.669**
- All other metrics (return, vol, IC, turnover, spread, alpha) unchanged.

---

## [0.3.0] — 2026-04-25

### Added
- `tests/test_table_utils.py`: 19 tests for `_table_utils.save_table_png`.
- `tests/test_step07_charts.py`: 18 tests for `make_nav` and `shade_regimes`.
- Full flake8 clean pass: removed unused imports (`mpatches`, `np` in `_table_utils`,
  `np` in `step04_turnover`), fixed F541 f-strings without placeholders across six
  scripts, removed unused `fail_idx` variable in `step09_long_short`, fixed E225/E231
  inside f-string expressions.
- `pyproject.toml`: added `[tool.coverage.*]` config and `[tool.pytest.ini_options]`.
- `.flake8`: added `E402` to `extend-ignore` (unavoidable for `sys.path.insert` pattern).

### Changed
- Factor weights updated throughout to **35% Value / 35% Quality / 30% Momentum**
  (previously 40/40/20).
- README results table updated to reflect 35/35/30 backtest numbers.
- All nine pipeline scripts reformatted by `black --line-length 100`.

---

## [0.2.0] — 2026-04-22

### Added
- Steps 03–09: full Phase 2 analytics pipeline (IC, turnover, buffer zone,
  benchmark comparison, final charts, factor attribution, long-short backtest).
- `_table_utils.py`: shared `save_table_png()` utility for styled PNG tables.
- `api/`: FastAPI + DuckDB REST API with 8 endpoints over result CSVs.
- `dashboard/`: Streamlit 4-page interactive dashboard.
- Sphinx documentation skeleton (`docs/`).
- Unit tests for steps 02–09 (204 tests at 100% coverage on computation code).

### Changed
- `step02_extend_2015.py`: switched from annual to quarterly rebalancing;
  added momentum score computation; extended universe to Dec 2025 (40 quarters).

---

## [0.1.0] — 2026-04-14

### Added
- Initial CW2 scaffold: `main.py` orchestrator, `step01_wrds_pull.py`,
  `step02_extend_2015.py` Phase 1 data build.
- `pyproject.toml` with Poetry dependency declarations.
- `.gitignore` excluding result CSVs, price cache, and exploratory scripts.
