from __future__ import annotations

"""Static normal-weight baseline built on the same CW2 factor stack.

``static_baseline`` is the tradable construction-layer control. Unlike the
gross ``universe_ew`` opportunity-set comparison, this path is charged the
configured trading cost because it is intended to represent an implementable
counterfactual portfolio built from the same CW2 factor stack and rebalance
process.
"""

from copy import deepcopy
from typing import Any, Dict, List, Tuple

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine
from team_Pearson.coursework_two.modules.backtest.data_loader import (
    load_adjusted_close_prices,
    load_trading_calendar,
)
from team_Pearson.coursework_two.modules.backtest.execution import (
    compute_drifted_weights,
    compute_period_simple_returns,
    compute_turnover,
    transaction_cost_from_turnover,
)
from team_Pearson.coursework_two.modules.backtest.performance import (
    compute_gross_return,
    compute_net_return,
    update_nav,
)
from team_Pearson.coursework_two.modules.feature.composite_alpha import compute_composite_alpha
from team_Pearson.coursework_two.modules.portfolio.construction import build_portfolio_targets

_SCHEMA = "systematic_equity"


def build_static_baseline_path(
    run_context: Dict[str, Any],
    db_engine: Engine,
    period_regimes: Dict[Any, Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[Any, Dict[str, float]]]:
    """Build the net-of-cost static-baseline NAV and target-weight history."""
    run_id = str(run_context["run_id"])
    cfg = deepcopy(run_context["config"])
    analysis_cfg = run_context["analysis_config"]
    cfg.setdefault("regime", {})
    cfg["regime"]["normal"] = deepcopy(analysis_cfg["static_baseline_normal_weights"])
    cfg["regime"]["stress"] = deepcopy(analysis_cfg["static_baseline_normal_weights"])
    cfg["regime"]["mode"] = "threshold"
    portfolio_cfg = cfg.setdefault("portfolio_construction", {})
    portfolio_cfg["weighting"] = "equal"
    portfolio_cfg["portfolio_name"] = "cw2_static_baseline"

    trading_calendar = load_trading_calendar(
        db_engine,
        run_context["run_row"]["start_date"],
        run_context["run_row"]["end_date"],
        benchmark_ticker=str(run_context["run_row"]["benchmark_ticker"]),
    )
    per_date = _load_static_inputs(run_context, db_engine)
    nav = 1.0
    rows: List[Dict[str, Any]] = []
    weight_history: Dict[Any, Dict[str, float]] = {}
    previous_positions: List[Dict[str, Any]] = []
    previous_returns: Dict[str, float] = {}

    for period in run_context["periods"]:
        rebalance_date = period["rebalance_date"]
        bundle = per_date.get(rebalance_date, {})
        factor_scores = _recompute_static_alpha(bundle.get("factor_scores", []), cfg)
        targets = build_portfolio_targets(
            factor_scores,
            bundle.get("risk_overlay", []),
            bundle.get("universe_screen", []),
            bundle.get("company_info", {}),
            previous_positions=previous_positions,
            config=cfg,
        )
        target_weights = {
            str(row["symbol"]): float(row["target_weight"])
            for row in targets
            if row.get("target_weight") is not None
        }
        weight_history[rebalance_date] = dict(target_weights)
        prev_lookup = {
            str(row["symbol"]): float(row["target_weight"])
            for row in previous_positions
            if row.get("target_weight") is not None
        }
        drifted_weights = compute_drifted_weights(prev_lookup, previous_returns)
        turnover, _ = compute_turnover(target_weights, drifted_weights)
        cost = transaction_cost_from_turnover(
            turnover, float(analysis_cfg["static_baseline_cost_bps"])
        )
        period_returns: Dict[str, float] = {}
        if target_weights:
            price_panel = load_adjusted_close_prices(
                db_engine,
                sorted(target_weights),
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
            gross_return = compute_gross_return(target_weights, period_returns)
        else:
            gross_return = 0.0
        net_return = compute_net_return(gross_return, cost)
        nav = update_nav(nav, gross_return, cost)
        regime_row = period_regimes.get(period["period_end_date"], {})
        rows.append(
            {
                "run_id": run_id,
                "execution_date": period["execution_date"],
                "period_end_date": period["period_end_date"],
                "series_name": "static_baseline",
                "nav": nav,
                "gross_return": gross_return,
                "period_return": net_return,
                "risk_free_return": period.get("risk_free_return"),
                "turnover": turnover,
                "gross_turnover": turnover * 2.0,
                "transaction_cost": cost,
                "num_holdings": len(target_weights),
                "regime": regime_row.get("regime"),
            }
        )
        previous_positions = [
            {"symbol": symbol, "target_weight": weight} for symbol, weight in target_weights.items()
        ]
        previous_returns = {
            symbol: float(period_returns.get(symbol, 0.0)) for symbol in target_weights
        }
    return rows, weight_history


def build_static_baseline_nav(
    run_context: Dict[str, Any],
    db_engine: Engine,
    period_regimes: Dict[Any, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build only the NAV series wrapper for existing callers."""
    rows, _ = build_static_baseline_path(run_context, db_engine, period_regimes)
    return rows


def _recompute_static_alpha(
    factor_scores: List[Dict[str, Any]], config: Dict[str, Any]
) -> List[Dict[str, Any]]:
    records = [dict(row) for row in factor_scores]
    if not records:
        return []
    return compute_composite_alpha(records, vix_level=None, config=config, forced_regime="normal")


def _load_static_inputs(
    run_context: Dict[str, Any], db_engine: Engine
) -> Dict[Any, Dict[str, Any]]:
    dates = [period["rebalance_date"] for period in run_context["periods"]]

    factor_sql = text(f"""
        SELECT as_of_date, symbol, quality_score, value_score, market_technical_score,
               sentiment_score, dividend_score, composite_alpha, regime
        FROM {_SCHEMA}.feature_factor_scores
        WHERE as_of_date = ANY(:dates)
        """)
    risk_sql = text(f"""
        SELECT as_of_date, symbol, pass_all, volatility_60d, missing_factor_pct, factor_groups_present
        FROM {_SCHEMA}.feature_risk_overlay
        WHERE as_of_date = ANY(:dates)
        """)
    universe_sql = text(f"""
        SELECT as_of_date, symbol, pass_all, country, gics_sector, log_market_cap, liquidity_20d
        FROM {_SCHEMA}.feature_universe_screen
        WHERE as_of_date = ANY(:dates)
        """)
    company_sql = text(f"""
        SELECT symbol, COALESCE(gics_sector, 'Unknown') AS gics_sector, country
        FROM {_SCHEMA}.company_static
        """)
    with db_engine.connect() as conn:
        factor_df = pd.DataFrame(conn.execute(factor_sql, {"dates": dates}).mappings().all())
        risk_df = pd.DataFrame(conn.execute(risk_sql, {"dates": dates}).mappings().all())
        universe_df = pd.DataFrame(conn.execute(universe_sql, {"dates": dates}).mappings().all())
        company_df = pd.DataFrame(conn.execute(company_sql).mappings().all())

    company_map = (
        {
            str(row["symbol"]): {
                "gics_sector": row.get("gics_sector"),
                "country": row.get("country"),
            }
            for row in company_df.to_dict(orient="records")
        }
        if not company_df.empty
        else {}
    )

    out: Dict[Any, Dict[str, Any]] = {}
    for dt in dates:
        factor_rows = (
            factor_df[factor_df["as_of_date"] == dt].to_dict(orient="records")
            if not factor_df.empty
            else []
        )
        risk_rows = (
            risk_df[risk_df["as_of_date"] == dt]
            .drop(columns=["as_of_date"])
            .to_dict(orient="records")
            if not risk_df.empty
            else []
        )
        universe_rows = (
            universe_df[universe_df["as_of_date"] == dt]
            .drop(columns=["as_of_date"])
            .to_dict(orient="records")
            if not universe_df.empty
            else []
        )
        out[dt] = {
            "factor_scores": factor_rows,
            "risk_overlay": risk_rows,
            "universe_screen": universe_rows,
            "company_info": company_map,
        }
    return out
