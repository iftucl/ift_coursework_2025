"""FastAPI application — Team RUSSEL Systematic Equity Strategy.

Serves factor model results via REST endpoints backed by DuckDB.

Run:
    cd team_russell/coursework_one
    poetry run uvicorn api.main:app --app-dir ../coursework_two --reload --port 8000

Docs: http://localhost:8000/docs
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import queries as q

app = FastAPI(
    title="RUSSEL Factor Strategy API",
    description=(
        "REST API for the Team RUSSEL 3-Factor Systematic Equity Strategy. "
        "Backed by DuckDB analytical queries over backtested portfolio data."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
def health():
    """Liveness check."""
    return {"status": "ok", "service": "RUSSEL Factor Strategy API"}


# ── Performance ───────────────────────────────────────────────────────────────

@app.get("/api/performance/summary", tags=["Performance"])
def performance_summary():
    """Top-level strategy KPIs: Q1 return, Sharpe, IC hit rate, Q1-Q5 spread."""
    return q.get_summary_stats()


@app.get("/api/performance/quintiles", tags=["Performance"])
def performance_quintiles():
    """Annualised net return, volatility, Sharpe and hit rate for all 5 quintiles."""
    return q.get_quintile_summary()


@app.get("/api/performance/annual", tags=["Performance"])
def performance_annual():
    """Q1 vs Q5 average quarterly net return by calendar year (2016–2025)."""
    return q.get_annual_performance()


# ── IC Analysis ───────────────────────────────────────────────────────────────

@app.get("/api/ic/summary", tags=["IC Analysis"])
def ic_summary():
    """Mean IC, ICIR, and hit rate across all periods."""
    return q.get_ic_summary()


@app.get("/api/ic/series", tags=["IC Analysis"])
def ic_series():
    """IC value per quarter with p-value and significance flag."""
    return q.get_ic_series()


# ── Factor Scores ─────────────────────────────────────────────────────────────

@app.get("/api/dates", tags=["Factor Scores"])
def rebalance_dates():
    """All available rebalance dates (most recent first)."""
    return q.get_rebalance_dates()


@app.get("/api/stocks", tags=["Factor Scores"])
def stocks(
    date: str = Query(..., description="Rebalance date, e.g. 2025-09-30"),
    quintile: int | None = Query(None, ge=1, le=5, description="Filter by quintile (1=best)"),
    limit: int = Query(50, ge=1, le=500),
):
    """Return stocks for a rebalance date with composite and factor scores."""
    dates = q.get_rebalance_dates()
    if date not in dates:
        raise HTTPException(status_code=404, detail=f"Date {date} not found. "
                            f"Use /api/dates to see available dates.")
    return q.get_stocks_by_date_quintile(date, quintile, limit)
