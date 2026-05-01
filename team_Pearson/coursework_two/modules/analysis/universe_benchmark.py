from __future__ import annotations

"""Secondary opportunity-set comparison using the investable universe EW basket.

``universe_ew`` is intentionally treated as a gross same-universe reference
index, not as the main tradable strategy alternative. It answers whether the
factor and construction stack add value beyond naive equal-weight exposure to
the same investable opportunity set. The tradable construction-layer control is
``static_baseline`` and is handled in ``static_baseline.py`` with configured
trading costs.
"""

from typing import Any, Dict, List, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Engine
from team_Pearson.coursework_two.modules.backtest.data_loader import load_adjusted_close_prices
from team_Pearson.coursework_two.modules.backtest.execution import compute_period_simple_returns

_SCHEMA = "systematic_equity"


def build_universe_ew_path(
    run_context: Dict[str, Any],
    db_engine: Engine,
    period_regimes: Dict[Any, Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[Any, Dict[str, float]]]:
    """Build the gross investable-universe equal-weight comparison path."""
    run_id = str(run_context["run_id"])
    periods = run_context["periods"]
    if not periods:
        return [], {}

    trading_calendar = _load_trading_calendar(run_context, db_engine)
    symbols_by_date = _load_universe_symbols(run_context, db_engine)
    nav = 1.0
    rows: List[Dict[str, Any]] = []
    weight_history: Dict[Any, Dict[str, float]] = {}
    for period in periods:
        rebalance_date = period["rebalance_date"]
        symbols = symbols_by_date.get(rebalance_date, [])
        weights = {sym: 1.0 / float(len(symbols)) for sym in symbols} if symbols else {}
        weight_history[rebalance_date] = weights
        if symbols:
            price_panel = load_adjusted_close_prices(
                db_engine,
                symbols,
                period["execution_date"],
                period["period_end_date"],
                lookback_days=5,
            )
            period_returns, _ = compute_period_simple_returns(
                price_panel,
                trading_calendar,
                period["execution_date"],
                period["period_end_date"],
                max_forward_fill_days=5,
            )
            equal_weight_return = sum(
                period_returns.get(sym, 0.0) * weights.get(sym, 0.0) for sym in symbols
            )
        else:
            equal_weight_return = 0.0
        nav *= 1.0 + equal_weight_return
        regime_row = period_regimes.get(period["period_end_date"], {})
        rows.append(
            {
                "run_id": run_id,
                "execution_date": period["execution_date"],
                "period_end_date": period["period_end_date"],
                "series_name": "universe_ew",
                "nav": nav,
                "period_return": equal_weight_return,
                "gross_return": None,
                "risk_free_return": period.get("risk_free_return"),
                "turnover": None,
                "gross_turnover": None,
                "transaction_cost": None,
                "num_holdings": len(symbols),
                "regime": regime_row.get("regime"),
            }
        )
    return rows, weight_history


def build_universe_ew_nav(
    run_context: Dict[str, Any],
    db_engine: Engine,
    period_regimes: Dict[Any, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build only the NAV series wrapper for existing callers."""
    rows, _ = build_universe_ew_path(run_context, db_engine, period_regimes)
    return rows


def _load_universe_symbols(run_context: Dict[str, Any], db_engine: Engine) -> Dict[Any, List[str]]:
    dates = [period["rebalance_date"] for period in run_context["periods"]]
    sql = text(f"""
        SELECT as_of_date, symbol
        FROM {_SCHEMA}.feature_universe_screen
        WHERE as_of_date = ANY(:dates)
          AND pass_all = TRUE
        ORDER BY as_of_date, symbol
        """)
    with db_engine.connect() as conn:
        rows = conn.execute(sql, {"dates": dates}).mappings().all()
    out: Dict[Any, List[str]] = {dt: [] for dt in dates}
    for row in rows:
        out.setdefault(row["as_of_date"], []).append(str(row["symbol"]))
    return out


def _load_trading_calendar(run_context: Dict[str, Any], db_engine: Engine) -> List[Any]:
    from team_Pearson.coursework_two.modules.backtest.data_loader import load_trading_calendar

    run_row = run_context["run_row"]
    return load_trading_calendar(
        db_engine,
        run_row["start_date"],
        run_row["end_date"],
        benchmark_ticker=str(run_row["benchmark_ticker"]),
    )
