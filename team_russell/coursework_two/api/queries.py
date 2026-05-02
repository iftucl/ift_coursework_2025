"""DuckDB analytical queries over the CW2 result CSV files.

DuckDB reads the CSV files directly — no ETL step needed.
All queries return plain dicts/lists for FastAPI to serialise.
"""

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from _rf_rates import mean_rf_annual, rf_quarterly_series  # noqa: E402

RESULTS = Path(__file__).parent.parent / "results"

RETURNS_10Y = str(RESULTS / "stock_returns_10year.csv")
IC_CSV = str(RESULTS / "ic_analysis.csv")
TURNOVER = str(RESULTS / "turnover.csv")
BENCHMARK = str(RESULTS / "benchmark_comparison.csv")

TC_RT = 0.004  # round-trip transaction cost
RISK_FREE_ANNUAL = mean_rf_annual()  # mean 3mo T-bill (FRED DGS3MO) Dec 2015–Sep 2025


def _conn():
    """Return a fresh in-memory DuckDB connection (thread-safe, lightweight)."""
    return duckdb.connect()


# ── Performance ───────────────────────────────────────────────────────────────


def get_quintile_summary() -> list[dict]:
    """Annualised net return, vol, Sharpe and hit rate per quintile (10-year).

    Sharpe is computed using time-varying 3mo T-bill rates (FRED DGS3MO) to
    match the pipeline methodology: excess_q = r_q - rf_q per quarter,
    Sharpe = mean(excess_q) * 4 / ann_vol.
    """
    con = _conn()
    # Fetch per-period returns so Python can apply time-varying Rf
    rows = con.execute(
        f"""
        SELECT
            CAST(quintile AS INTEGER) AS quintile,
            start_date,
            AVG(gross_return) - {TC_RT} AS net_return,
            SUM(CASE WHEN gross_return - {TC_RT} > 0 THEN 1 ELSE 0 END) * 1.0
                / COUNT(*) AS pos_frac
        FROM read_csv_auto('{RETURNS_10Y}')
        WHERE quintile IS NOT NULL
        GROUP BY quintile, start_date
        ORDER BY quintile, start_date
    """
    ).fetchall()

    df = pd.DataFrame(rows, columns=["quintile", "start_date", "net_return", "pos_frac"])
    df["start_date"] = pd.to_datetime(df["start_date"])

    result = []
    for q, grp in df.groupby("quintile"):
        r = grp["net_return"]
        ann_ret = (1 + r.mean()) ** 4 - 1
        ann_vol = r.std(ddof=1) * np.sqrt(4)
        rf_q = rf_quarterly_series(grp["start_date"])
        excess = r.values - rf_q.values
        ann_excess = float(np.mean(excess)) * 4
        sharpe = ann_excess / ann_vol if ann_vol > 0 else np.nan
        downside = np.minimum(excess, 0)
        down_dev = np.sqrt(np.mean(downside**2)) * np.sqrt(4)
        sortino = ann_excess / down_dev if down_dev > 0 else np.nan
        hit_rate = (r > 0).mean()
        result.append(
            {
                "quintile": int(q),
                "n_periods": len(r),
                "avg_quarterly_net_pct": round(float(r.mean()) * 100, 3),
                "ann_net_return_pct": round(ann_ret * 100, 2),
                "ann_vol_pct": round(ann_vol * 100, 2),
                "sharpe_ratio": round(sharpe, 3),
                "sortino_ratio": round(sortino, 3),
                "hit_rate_pct": round(hit_rate * 100, 1),
            }
        )
    return result


def get_annual_performance() -> list[dict]:
    """Q1 and Q5 average quarterly net return by calendar year (end-date year)."""
    con = _conn()
    rows = con.execute(
        f"""
        WITH period_avg AS (
            SELECT
                YEAR(CAST(end_date AS DATE))    AS year,
                CAST(quintile AS INTEGER)        AS quintile,
                AVG(gross_return) - {TC_RT}     AS net_return
            FROM read_csv_auto('{RETURNS_10Y}')
            WHERE quintile IN (1, 5)
            GROUP BY year, quintile, start_date, end_date
        ),
        by_year AS (
            SELECT
                year,
                quintile,
                AVG(net_return)  AS avg_qtrly_net,
                COUNT(*)         AS n_quarters
            FROM period_avg
            GROUP BY year, quintile
        ),
        pivoted AS (
            SELECT
                year,
                MAX(CASE WHEN quintile = 1 THEN ROUND(avg_qtrly_net * 100, 2) END) AS q1_avg_pct,
                MAX(CASE WHEN quintile = 5 THEN ROUND(avg_qtrly_net * 100, 2) END) AS q5_avg_pct,
                MAX(n_quarters) AS n_quarters
            FROM by_year
            GROUP BY year
        )
        SELECT year, q1_avg_pct, q5_avg_pct,
               ROUND(q1_avg_pct - q5_avg_pct, 2) AS spread_pct,
               n_quarters
        FROM pivoted
        ORDER BY year
    """
    ).fetchall()
    cols = ["year", "q1_avg_pct", "q5_avg_pct", "spread_pct", "n_quarters"]
    return [dict(zip(cols, r)) for r in rows]


def get_summary_stats() -> dict:
    """Top-level KPIs for the strategy."""
    quintiles = get_quintile_summary()
    q1 = next(q for q in quintiles if q["quintile"] == 1)
    q5 = next(q for q in quintiles if q["quintile"] == 5)
    annual = get_annual_performance()
    years_positive = sum(1 for y in annual if (y["spread_pct"] or 0) > 0)
    return {
        "model": "3-Factor (Value 35% + Quality 35% + Momentum 30%)",
        "backtest_periods": q1["n_periods"],
        "backtest_start": "2015-12-31",
        "backtest_end": "2025-12-31",
        "q1_ann_net_return_pct": q1["ann_net_return_pct"],
        "q1_sharpe_ratio": q1["sharpe_ratio"],
        "q1_hit_rate_pct": q1["hit_rate_pct"],
        "q1_q5_spread_pct": round(q1["ann_net_return_pct"] - q5["ann_net_return_pct"], 2),
        "annual_hit_rate_pct": round(years_positive / len(annual) * 100, 1),
        "transaction_cost_pct": TC_RT * 100,
    }


# ── IC Analysis ───────────────────────────────────────────────────────────────


def get_ic_series() -> list[dict]:
    """IC per quarter computed from 10-year stock data using Spearman correlation."""
    con = _conn()
    # Compute Spearman IC per period using rank correlation approximation
    # corr(rank(score), rank(return)) = Spearman IC
    rows = con.execute(
        f"""
        WITH scored AS (
            SELECT
                start_date, end_date,
                composite_score AS score,
                gross_return - {TC_RT} AS net_return
            FROM read_csv_auto('{RETURNS_10Y}')
            WHERE composite_score IS NOT NULL
              AND gross_return IS NOT NULL
              AND quintile IS NOT NULL
        ),
        ranked AS (
            SELECT
                start_date, end_date,
                RANK() OVER (PARTITION BY start_date ORDER BY score) AS score_rank,
                RANK() OVER (PARTITION BY start_date ORDER BY net_return) AS ret_rank,
                COUNT(*) OVER (PARTITION BY start_date) AS n
            FROM scored
        ),
        period_ic AS (
            SELECT
                start_date, end_date,
                CORR(score_rank, ret_rank) AS ic,
                COUNT(*) AS n_stocks
            FROM ranked
            GROUP BY start_date, end_date
        )
        SELECT
            start_date,
            end_date,
            ROUND(ic * 100, 3) AS ic_pct,
            n_stocks
        FROM period_ic
        ORDER BY start_date
    """
    ).fetchall()
    cols = ["start_date", "end_date", "ic_pct", "n_stocks"]
    return [dict(zip(cols, r)) for r in rows]


def get_ic_summary() -> dict:
    """Mean IC, ICIR, hit rate across all 40 periods."""
    series = get_ic_series()
    ics = [r["ic_pct"] for r in series]
    n = len(ics)
    mean_ic = sum(ics) / n
    std_ic = (sum((x - mean_ic) ** 2 for x in ics) / (n - 1)) ** 0.5
    return {
        "mean_ic_pct": round(mean_ic, 3),
        "icir": round(mean_ic / std_ic, 3) if std_ic else 0,
        "hit_rate_pct": round(sum(1 for x in ics if x > 0) / len(ics) * 100, 1),
        "n_periods": len(ics),
    }


# ── Factor Scores Browser ─────────────────────────────────────────────────────


def get_rebalance_dates() -> list[str]:
    """All unique rebalance dates in the 10-year dataset."""
    con = _conn()
    rows = con.execute(
        f"""
        SELECT DISTINCT start_date
        FROM read_csv_auto('{RETURNS_10Y}')
        ORDER BY start_date DESC
    """
    ).fetchall()
    return [r[0] for r in rows]


def get_stocks_by_date_quintile(
    date: str, quintile: int | None = None, limit: int = 50
) -> list[dict]:
    """Return stocks for a given rebalance date, optionally filtered by quintile."""
    con = _conn()
    where = f"start_date = '{date}'"
    if quintile:
        where += f" AND CAST(quintile AS INTEGER) = {quintile}"
    rows = con.execute(
        f"""
        SELECT
            symbol,
            start_date,
            end_date,
            CAST(quintile AS INTEGER)                AS quintile,
            ROUND(composite_score, 4)                AS composite_score,
            ROUND(value_score, 4)                    AS value_score,
            ROUND(quality_score, 4)                  AS quality_score,
            ROUND(momentum_score, 4)                 AS momentum_score,
            ROUND(gross_return * 100, 2)             AS gross_return_pct,
            ROUND((gross_return - {TC_RT}) * 100, 2) AS net_return_pct
        FROM read_csv_auto('{RETURNS_10Y}')
        WHERE {where}
          AND quintile IS NOT NULL
        ORDER BY composite_score DESC
        LIMIT {limit}
    """
    ).fetchall()
    cols = [
        "symbol",
        "start_date",
        "end_date",
        "quintile",
        "composite_score",
        "value_score",
        "quality_score",
        "momentum_score",
        "gross_return_pct",
        "net_return_pct",
    ]
    return [dict(zip(cols, r)) for r in rows]
