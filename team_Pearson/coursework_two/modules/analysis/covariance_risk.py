from __future__ import annotations

"""Explicit covariance-aware portfolio risk diagnostics for CW2 analysis."""

import logging
from collections import defaultdict
from datetime import timedelta
from typing import Any, Dict, List, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Engine
from team_Pearson.coursework_two.modules.backtest.data_loader import (
    load_adjusted_close_prices,
    load_fundamental_exposure_observations,
    load_trading_calendar,
)
from team_Pearson.coursework_two.modules.risk.covariance import (
    align_weights,
    build_return_panel,
    covariance_method_label,
    covariance_quality,
    estimate_fundamental_factor_covariance,
    estimate_shrunk_covariance,
    ex_ante_tracking_error,
    is_factor_covariance_method,
    is_fundamental_covariance_method,
    lookback_start,
    normalize_weights,
    portfolio_risk_stats,
    weighted_average_pairwise_correlation,
)

_SCHEMA = "systematic_equity"
_ANNUALIZATION_FACTOR = 252.0
logger = logging.getLogger(__name__)


def compute_covariance_diagnostics(
    run_context: Dict[str, Any],
    db_engine: Engine,
    *,
    strategy_weights: Dict[Any, Dict[str, float]],
    universe_weights: Dict[Any, Dict[str, float]],
    static_weights: Dict[Any, Dict[str, float]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Compute ex-ante covariance-based risk diagnostics and contributions."""
    analysis_cfg = (run_context.get("analysis_config") or {}).get("covariance") or {}
    if not bool(analysis_cfg.get("enabled", True)):
        return [], []

    include_series = [
        str(name)
        for name in (
            analysis_cfg.get("include_series") or ["strategy", "universe_ew", "static_baseline"]
        )
    ]
    lookback_days = max(20, int(analysis_cfg.get("lookback_days", 252)))
    min_history_days = max(20, int(analysis_cfg.get("min_history_days", 126)))
    shrinkage_intensity = float(analysis_cfg.get("shrinkage_intensity", 0.25))
    covariance_method_name = str(analysis_cfg.get("method", "diagonal_shrinkage"))
    covariance_method_key = covariance_method_name.strip().lower()
    factor_count = analysis_cfg.get("factor_count", analysis_cfg.get("n_factors"))
    max_factor_count = max(1, int(analysis_cfg.get("max_factor_count", 5)))
    factor_variance_target_raw = analysis_cfg.get("factor_variance_target")
    factor_variance_target = (
        None if factor_variance_target_raw is None else float(factor_variance_target_raw)
    )
    specific_variance_floor_ratio = float(analysis_cfg.get("specific_variance_floor_ratio", 0.05))
    style_factors = analysis_cfg.get("style_factors")
    include_sector_factors = bool(analysis_cfg.get("include_sector_factors", True))
    exposure_lag_days = max(0, int(analysis_cfg.get("exposure_lag_days", 1)))
    max_exposure_staleness_days = max(0, int(analysis_cfg.get("max_exposure_staleness_days", 540)))
    min_factor_return_days = max(5, int(analysis_cfg.get("min_factor_return_days", 40)))
    min_cross_section = max(3, int(analysis_cfg.get("min_cross_section", 8)))
    min_sector_members = max(1, int(analysis_cfg.get("min_sector_members", 2)))
    factor_ridge = float(analysis_cfg.get("factor_ridge", 1.0e-4))
    factor_cov_shrinkage = float(analysis_cfg.get("factor_cov_shrinkage", 0.10))
    fallback_to_statistical = bool(analysis_cfg.get("fallback_to_statistical_factor", True))
    fallback_to_diagonal = bool(analysis_cfg.get("fallback_to_diagonal_shrinkage", True))
    max_forward_fill_days = max(0, int(analysis_cfg.get("max_forward_fill_days", 5)))
    max_condition_number = float(analysis_cfg.get("max_condition_number", 1e8))
    relative_eigen_floor = float(analysis_cfg.get("relative_eigen_floor", 1e-10))
    absolute_eigen_floor = float(analysis_cfg.get("absolute_eigen_floor", 1e-12))
    primary_benchmark = str(run_context["analysis_config"].get("primary_benchmark", "SPY"))
    secondary_benchmark = str(
        run_context["analysis_config"].get("secondary_benchmark", "universe_ew")
    )
    requested_covariance_method = covariance_method_label(
        covariance_method_key, shrinkage_intensity
    )

    run_row = run_context["run_row"]
    trading_calendar = load_trading_calendar(
        db_engine,
        run_row["start_date"] - timedelta(days=max(lookback_days * 2, 550)),
        run_row["end_date"],
        benchmark_ticker=str(run_row["benchmark_ticker"]),
    )
    sector_map = _load_sector_map(db_engine)
    series_weights = {
        "strategy": strategy_weights,
        "universe_ew": universe_weights,
        "static_baseline": static_weights,
    }

    metric_rows: List[Dict[str, Any]] = []
    contribution_rows: List[Dict[str, Any]] = []

    for period in run_context["periods"]:
        rebalance_date = period["rebalance_date"]
        period_end_date = period["period_end_date"]
        active_maps = {
            series_name: normalize_weights(
                series_weights.get(series_name, {}).get(rebalance_date, {})
            )
            for series_name in include_series
        }
        union_symbols = sorted({sym for weights in active_maps.values() for sym in weights})
        if not union_symbols:
            continue

        start_date = lookback_start(
            trading_calendar, rebalance_date, lookback_days, max_forward_fill_days
        )
        price_panel = load_adjusted_close_prices(
            db_engine,
            union_symbols,
            start_date,
            rebalance_date,
            lookback_days=max_forward_fill_days,
        )
        returns = build_return_panel(
            price_panel,
            trading_calendar=trading_calendar,
            start_date=start_date,
            end_date=rebalance_date,
            lookback_days=lookback_days,
            min_history_days=min_history_days,
            max_forward_fill_days=max_forward_fill_days,
        )
        if returns.empty:
            continue

        period_covariance_method = requested_covariance_method
        if is_fundamental_covariance_method(covariance_method_key):
            exposure_observations = load_fundamental_exposure_observations(
                db_engine,
                union_symbols,
                start_date,
                rebalance_date,
                max_staleness_days=max_exposure_staleness_days,
            )
            covariance = estimate_fundamental_factor_covariance(
                returns,
                exposure_observations,
                sector_map=sector_map,
                style_factors=style_factors,
                include_sector_factors=include_sector_factors,
                exposure_lag_days=exposure_lag_days,
                max_exposure_staleness_days=max_exposure_staleness_days,
                min_cross_section=min_cross_section,
                min_factor_return_days=min_factor_return_days,
                min_sector_members=min_sector_members,
                factor_ridge=factor_ridge,
                factor_cov_shrinkage=factor_cov_shrinkage,
                specific_variance_floor_ratio=specific_variance_floor_ratio,
            )
        else:
            covariance = estimate_shrunk_covariance(
                returns,
                shrinkage_intensity=shrinkage_intensity,
                method=covariance_method_name,
                factor_count=None if factor_count is None else int(factor_count),
                max_factor_count=max_factor_count,
                factor_variance_target=factor_variance_target,
                specific_variance_floor_ratio=specific_variance_floor_ratio,
            )
        quality = covariance_quality(
            covariance,
            max_condition_number=max_condition_number,
            relative_eigen_floor=relative_eigen_floor,
            absolute_eigen_floor=absolute_eigen_floor,
        )
        if (
            not bool(quality.get("is_usable"))
            and is_fundamental_covariance_method(covariance_method_key)
            and fallback_to_statistical
        ):
            fallback_covariance = estimate_shrunk_covariance(
                returns,
                shrinkage_intensity=shrinkage_intensity,
                method="statistical_factor",
                factor_count=None if factor_count is None else int(factor_count),
                max_factor_count=max_factor_count,
                factor_variance_target=factor_variance_target,
                specific_variance_floor_ratio=specific_variance_floor_ratio,
            )
            fallback_quality = covariance_quality(
                fallback_covariance,
                max_condition_number=max_condition_number,
                relative_eigen_floor=relative_eigen_floor,
                absolute_eigen_floor=absolute_eigen_floor,
            )
            if not fallback_covariance.empty and bool(fallback_quality.get("is_usable")):
                logger.warning(
                    "covariance_diagnostics: fallback from method=%s to statistical_factor rebalance_date=%s reason=%s",
                    covariance_method_key,
                    rebalance_date,
                    quality.get("reason"),
                )
                covariance = fallback_covariance
                quality = fallback_quality
                period_covariance_method = covariance_method_label(
                    "statistical_factor", shrinkage_intensity
                )
        if (
            not bool(quality.get("is_usable"))
            and is_factor_covariance_method(covariance_method_key)
            and fallback_to_diagonal
        ):
            fallback_covariance = estimate_shrunk_covariance(
                returns,
                shrinkage_intensity=shrinkage_intensity,
                method="diagonal_shrinkage",
            )
            fallback_quality = covariance_quality(
                fallback_covariance,
                max_condition_number=max_condition_number,
                relative_eigen_floor=relative_eigen_floor,
                absolute_eigen_floor=absolute_eigen_floor,
            )
            if not fallback_covariance.empty and bool(fallback_quality.get("is_usable")):
                logger.warning(
                    "covariance_diagnostics: fallback from method=%s to diagonal_shrinkage rebalance_date=%s reason=%s",
                    covariance_method_key,
                    rebalance_date,
                    quality.get("reason"),
                )
                covariance = fallback_covariance
                quality = fallback_quality
                period_covariance_method = covariance_method_label(
                    "diagonal_shrinkage", shrinkage_intensity
                )
        if not bool(quality.get("is_usable")):
            logger.warning(
                "covariance_diagnostics: skipped rebalance_date=%s reason=%s condition_number=%s",
                rebalance_date,
                quality.get("reason"),
                quality.get("condition_number"),
            )
            continue

        aligned_maps = {
            series_name: align_weights(weights, covariance.columns)
            for series_name, weights in active_maps.items()
        }

        for series_name, weights in aligned_maps.items():
            if not weights:
                continue
            risk_stats = portfolio_risk_stats(weights, covariance, sector_map)
            metric_rows.extend(
                _build_metric_rows(
                    run_id=str(run_context["run_id"]),
                    rebalance_date=rebalance_date,
                    period_end_date=period_end_date,
                    series_name=series_name,
                    covariance_method=period_covariance_method,
                    lookback_days=lookback_days,
                    risk_stats=risk_stats,
                )
            )
            contribution_rows.extend(
                _build_contribution_rows(
                    run_id=str(run_context["run_id"]),
                    rebalance_date=rebalance_date,
                    period_end_date=period_end_date,
                    series_name=series_name,
                    covariance_method=period_covariance_method,
                    lookback_days=lookback_days,
                    risk_stats=risk_stats,
                )
            )

            risk_benchmark = next(
                (
                    candidate
                    for candidate in [
                        primary_benchmark,
                        secondary_benchmark,
                        "universe_ew",
                    ]
                    if candidate in aligned_maps
                ),
                None,
            )
            if risk_benchmark is not None and series_name != risk_benchmark:
                benchmark_weights = aligned_maps.get(risk_benchmark, {})
                if benchmark_weights:
                    te_ann = ex_ante_tracking_error(weights, benchmark_weights, covariance)
                    metric_rows.append(
                        {
                            "run_id": str(run_context["run_id"]),
                            "rebalance_date": rebalance_date,
                            "period_end_date": period_end_date,
                            "series_name": series_name,
                            "versus_series": risk_benchmark,
                            "metric_name": "ex_ante_tracking_error_ann",
                            "metric_value": None if te_ann is None else te_ann * 100.0,
                            "metric_unit": "%",
                            "covariance_method": period_covariance_method,
                            "lookback_days": lookback_days,
                        }
                    )

    return metric_rows, contribution_rows


def _build_metric_rows(
    *,
    run_id: str,
    rebalance_date: Any,
    period_end_date: Any,
    series_name: str,
    covariance_method: str,
    lookback_days: int,
    risk_stats: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if not risk_stats:
        return []
    raw_metrics = [
        ("n_assets", risk_stats.get("n_assets"), "-"),
        ("ex_ante_volatility_ann", risk_stats.get("annualized_volatility"), "%"),
        ("diversification_ratio", risk_stats.get("diversification_ratio"), "x"),
        ("effective_risk_bets", risk_stats.get("effective_risk_bets"), "x"),
        ("avg_pairwise_correlation", risk_stats.get("avg_pairwise_correlation"), "-"),
        ("top_asset_risk_share", risk_stats.get("top_asset_risk_share"), "%"),
        ("top_sector_risk_share", risk_stats.get("top_sector_risk_share"), "%"),
    ]
    rows: List[Dict[str, Any]] = []
    for metric_name, raw_value, unit in raw_metrics:
        if raw_value is None:
            continue
        if unit == "%":
            metric_value = float(raw_value) * 100.0
        else:
            metric_value = float(raw_value)
        rows.append(
            {
                "run_id": run_id,
                "rebalance_date": rebalance_date,
                "period_end_date": period_end_date,
                "series_name": series_name,
                "versus_series": "",
                "metric_name": metric_name,
                "metric_value": metric_value,
                "metric_unit": unit,
                "covariance_method": covariance_method,
                "lookback_days": lookback_days,
            }
        )
    return rows


def _build_contribution_rows(
    *,
    run_id: str,
    rebalance_date: Any,
    period_end_date: Any,
    series_name: str,
    covariance_method: str,
    lookback_days: int,
    risk_stats: Dict[str, Any],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in risk_stats.get("asset_contributions", []) + risk_stats.get(
        "sector_contributions", []
    ):
        rows.append(
            {
                "run_id": run_id,
                "rebalance_date": rebalance_date,
                "period_end_date": period_end_date,
                "series_name": series_name,
                "dimension_type": row["dimension_type"],
                "dimension_name": row["dimension_name"],
                "portfolio_weight": row["portfolio_weight"],
                "risk_contribution_pct": row["risk_contribution_pct"],
                "component_volatility_contribution": row["component_volatility_contribution"],
                "covariance_method": covariance_method,
                "lookback_days": lookback_days,
            }
        )
    return rows


def _load_strategy_weights(run_id: str, db_engine: Engine) -> Dict[Any, Dict[str, float]]:
    sql = text(f"""
        SELECT rebalance_date, symbol, target_weight
        FROM {_SCHEMA}.backtest_holdings
        WHERE run_id = :run_id
        ORDER BY rebalance_date, symbol
        """)
    with db_engine.connect() as conn:
        rows = conn.execute(sql, {"run_id": run_id}).mappings().all()
    out: Dict[Any, Dict[str, float]] = defaultdict(dict)
    for row in rows:
        weight = float(row["target_weight"]) if row.get("target_weight") is not None else 0.0
        if weight > 0:
            out[row["rebalance_date"]][str(row["symbol"])] = weight
    return {dt: normalize_weights(weights) for dt, weights in out.items()}


def load_weight_sets(
    run_context: Dict[str, Any],
    db_engine: Engine,
    *,
    universe_weights: Dict[Any, Dict[str, float]],
    static_weights: Dict[Any, Dict[str, float]],
) -> Dict[str, Dict[Any, Dict[str, float]]]:
    """Load all relevant portfolio weight maps for covariance diagnostics."""
    return {
        "strategy": _load_strategy_weights(str(run_context["run_id"]), db_engine),
        "universe_ew": universe_weights,
        "static_baseline": static_weights,
    }


def _load_sector_map(db_engine: Engine) -> Dict[str, str]:
    sql = text(f"""
        SELECT symbol, COALESCE(gics_sector, 'Unknown') AS gics_sector
        FROM {_SCHEMA}.company_static
        """)
    with db_engine.connect() as conn:
        rows = conn.execute(sql).mappings().all()
    return {str(row["symbol"]): str(row["gics_sector"]) for row in rows}


_estimate_covariance = estimate_shrunk_covariance
_ex_ante_tracking_error = ex_ante_tracking_error
_portfolio_risk_stats = portfolio_risk_stats
_weighted_average_pairwise_correlation = weighted_average_pairwise_correlation


__all__ = [
    "compute_covariance_diagnostics",
    "load_weight_sets",
    "_estimate_covariance",
    "_ex_ante_tracking_error",
    "_portfolio_risk_stats",
    "_weighted_average_pairwise_correlation",
]
