# Coursework Two — Systematic Equity Strategy
**Team RUSSEL | UCL IFT Big Data in Quantitative Finance**

---

## Strategy Overview

A **3-factor long-only systematic equity strategy** combining Value, Quality, and Momentum signals, backtested over **40 quarterly periods (Dec 2015 – Dec 2025)** across a mixed US and European large-cap universe of up to 597 companies.

The portfolio ranks all eligible stocks by a composite factor score, selects the top 20% (Q1, ~119 stocks), weights them equally, and rebalances every quarter. Transaction costs of 0.4% round-trip are applied at every rebalance.

**Factor weights:** Value 35% + Quality 35% + Momentum 30%

**Final results:**

| Metric | Value |
|---|---|
| Backtest period | Dec 2015 – Dec 2025 (40 quarters) |
| Q1 annualised net return | 13.48% p.a. |
| Q1 annualised volatility | 16.19% |
| Q1 Sharpe ratio (net of Rf) | 0.660 |
| Q1 Sortino ratio | 1.011 |
| Q1 max drawdown | 25.64% |
| Q1 hit rate (quarters positive) | 77.5% (31 of 40 quarters) |
| Q1-Q5 spread | +1.51% p.a. |
| IC hit rate | 47.5% (19 of 40 quarters) |
| ICIR | 0.114 |
| Avg quarterly turnover | 29.0% |
| Buffer-zone Sharpe (robustness) | 0.669 |
| Alpha vs EW universe | +1.06% p.a. |

---

## How to Run

All commands run from `team_russell/coursework_one/`:

```bash
cd team_russell/coursework_one

# Run full pipeline (steps 02–09); step 01 skipped by default (needs WRDS)
poetry run python ../coursework_two/main.py

# Run tests with coverage report
poetry run pytest ../coursework_two/tests/ \
    --cov=../coursework_two/scripts \
    --cov-config=../coursework_two/pyproject.toml \
    --cov-report=term-missing
```

---

## Pipeline

### Phase 1 — Data Build _(run once; requires PostgreSQL + WRDS)_

| Step | Script | What it does | Output |
|---|---|---|---|
| 01 | `step01_wrds_pull.py` _(needs WRDS credentials)_ | Pull quarterly TTM fundamentals from WRDS (`comp.g_fundq`), 45-day lag, upsert all 40 dates | PostgreSQL `factor_values` |
| 02 | `step02_extend_2015.py` | Extend to Dec 2015 — builds the primary 40-quarter dataset | `stock_returns_10year.csv` |

### Phase 2 — Analysis _(all read `stock_returns_10year.csv`; no DB required)_

| Step | Script | What it does | Output |
|---|---|---|---|
| 03 | `step03_ic_analysis.py` | Spearman IC per quarter + quintile performance table | `ic_analysis.csv`, `03_ic_per_period.png` |
| 04 | `step04_turnover.py` | Q1 turnover per period + sector active weights | `turnover.csv`, `sector_weights.csv`, `06_turnover_per_period.png`, `07_sector_active_weights.png` |
| 05 | `step05_buffer_zone.py` | Buffer zone robustness test (15% entry / 25% exit) | `buffer_comparison.csv`, `05_buffer_zone.png` |
| 06 | `step06_benchmark.py` | Compare Q1 vs SPY / MSCI World / MSCI ACWI | `benchmark_comparison.csv`, `04_benchmark_comparison.png`, `05_benchmark_alpha.png` |
| 07 | `step07_final_charts.py` | Regenerate primary NAV charts + annual returns table | `01_10year_nav.png`, `02_q1_vs_q5.png`, `07c_q1_annual_returns_table.png` |
| 08 | `step08_factor_attribution.py` | Value vs Quality vs Momentum vs Composite | `factor_attribution.csv`, `08_factor_attribution_nav.png`, `09_factor_attribution_bar.png` |
| 09 | `step09_long_short.py` _(optional)_ | Long Q1 / Short Q5 robustness test | `long_short_returns.csv`, `10_long_short_cumulative.png`, `11_long_short_per_period.png`, `12_long_short_q1q5.png` |

---

## API & Dashboard

From `team_russell/coursework_one/`:

```bash
# FastAPI — http://localhost:8000/docs
poetry run uvicorn api.main:app --app-dir ../coursework_two --reload --port 8000

# Streamlit dashboard — http://localhost:8501
poetry run streamlit run ../coursework_two/dashboard/app.py
```

### API Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness check |
| `GET /api/performance/summary` | Top-level KPIs (Q1 return, Sharpe, spread) |
| `GET /api/performance/quintiles` | All 5 quintiles — return, vol, Sharpe, hit rate |
| `GET /api/performance/annual` | Q1 vs Q5 by calendar year (2016–2025) |
| `GET /api/ic/summary` | Mean IC, ICIR, hit rate |
| `GET /api/ic/series` | IC per quarter with significance flag |
| `GET /api/dates` | All 40 rebalance dates (most recent first) |
| `GET /api/stocks?date=&quintile=` | Stocks with factor scores at a given date |

### Dashboard Pages

| Page | Content |
|---|---|
| Overview | KPI cards + interactive 10-year NAV chart + benchmark comparison |
| Performance | Quintile table + annual Q1-Q5 spread + Sharpe chart |
| IC Analysis | IC per quarter (40 periods), coloured by positive/negative |
| Stock Browser | Filter by rebalance date and quintile, view factor scores |

---

## Output Structure

```
results/
  stock_returns_10year.csv      — PRIMARY: full 40-quarter dataset (step02)
  ic_analysis.csv               — IC per period (step03)
  turnover.csv                  — Q1 turnover per quarter (step04)
  sector_weights.csv            — Sector active weights (step04)
  buffer_comparison.csv         — Buffer zone vs original (step05)
  benchmark_comparison.csv      — Q1 vs SPY/URTH/ACWI (step06)
  factor_attribution.csv        — Single-factor vs composite (step08)
  long_short_returns.csv        — Long-short portfolio returns (step09, optional)
  charts/
    01_10year_nav.png               — PRIMARY: 10-year quintile NAV (step07)
    02_q1_vs_q5.png                 — Q1 vs Q5 comparison, 40 quarters (step07)
    03_ic_per_period.png            — IC per quarter, 40 periods (step03)
    04_benchmark_comparison.png     — Q1 vs S&P 500 / MSCI World / MSCI ACWI (step06)
    05_benchmark_alpha.png          — Q1 quarterly alpha vs benchmarks (step06)
    05_buffer_zone.png              — Buffer zone robustness test (step05)
    06_turnover_per_period.png      — Q1 turnover per quarter (step04)
    07_sector_active_weights.png    — Sector active weight heatmap (step04)
    07c_q1_annual_returns_table.png — Long-only Q1 annual return by year (step07)
    08_factor_attribution_nav.png   — Single-factor vs composite NAV (step08)
    09_factor_attribution_bar.png   — Per-quarter factor attribution (step08)
    10_long_short_cumulative.png    — Long-Short vs Long-Only vs EW NAV (step09)
    11_long_short_per_period.png    — Long-Short return per quarter (step09)
    12_long_short_q1q5.png          — Q1 vs Q5 gross returns per quarter (step09)

scripts/
  _rf_rates.py              — Time-varying 3mo T-bill rates (FRED DGS3MO) for all 40 periods

api/
  main.py     — FastAPI application (8 endpoints)
  queries.py  — DuckDB queries over result CSVs

dashboard/
  app.py      — Streamlit 4-page interactive dashboard

docs/
  CW2_Report_Draft.md         — Investment strategy report draft

tests/
  conftest.py                 — Shared pytest fixtures
  test_step02_computations.py — Unit tests: scoring helpers (build_composite, IC, momentum, …)
  test_step03_ic.py           — Unit tests: compute_ic, print_performance_table
  test_step04_turnover.py     — Unit tests: compute_turnover, compute_sector_weights
  test_step05_buffer.py       — Unit tests: buffer membership, returns, turnover
  test_step06_benchmark.py    — Unit tests: ann_stats, jensen_alpha, index_return
  test_step07_charts.py       — Unit tests: make_nav, shade_regimes, compute_annual_returns
  test_step08_attribution.py  — Unit tests: factor quintiles, portfolio returns, stats
  test_step09_longshort.py    — Unit tests: build_ls, ann_stats
  test_table_utils.py         — Unit tests: save_table_png
  test_rf_rates.py            — Unit tests: _rf_rates (get_rf_annual, rf_quarterly_series, …)
```

---

## Prerequisites

- PostgreSQL with `systematic_equity.factor_values` table (from CW1 pipeline)
- WRDS account with credentials in `~/.pgpass` (Step 01 only)
- Python 3.10+ via Poetry — dependencies declared in `pyproject.toml`
- Required packages installed via `poetry install` from `team_russell/coursework_one/`

## Testing

```bash
cd team_russell/coursework_one
poetry run pytest ../coursework_two/tests/ \
    --cov=../coursework_two/scripts \
    --cov-config=../coursework_two/pyproject.toml
# 244 tests — 100% coverage on testable computation code
```
