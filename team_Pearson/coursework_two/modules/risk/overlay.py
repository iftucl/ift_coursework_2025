"""Risk overlay — hard constraint filters that exclude stocks from the candidate pool.

These are NOT alpha factors. They act as binary pass/fail gates:

1. **Market cap filter**: exclude micro/small caps below threshold
2. **Liquidity filter**: exclude illiquid stocks (low 20-day avg dollar volume)
3. **Volatility filter**: exclude top N% most volatile stocks (60-day vol)
4. **Data quality filter**: exclude stocks missing too many sub-variable scores

Stocks that fail any filter are excluded from portfolio construction
regardless of their composite alpha score.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Defaults (overridden by config)
_DEFAULT_MIN_LOG_MARKET_CAP = 22.0  # ~ln($3.6B)
_DEFAULT_MIN_LIQUIDITY_20D = 5_000_000  # $5M
_DEFAULT_MAX_VOL_PERCENTILE = 0.95  # top 5% excluded
_DEFAULT_MAX_MISSING_FACTOR_PCT = 0.40  # >40% missing sub-vars excluded


def _expected_sub_variable_count(
    sub_score_records: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
    *,
    factor_groups: Optional[List[str]] = None,
) -> int:
    """Return expected sub-variable count from config, falling back to records."""
    factor_cfg = (config or {}).get("factors", {})
    allowed_groups = {str(group).strip() for group in (factor_groups or []) if str(group).strip()}
    configured_pairs = {
        (str(group), str(sub_var))
        for group, settings in factor_cfg.items()
        if not allowed_groups or str(group) in allowed_groups
        for sub_var in (settings.get("sub_variables") or [])
    }
    if configured_pairs:
        return len(configured_pairs)

    observed_pairs = {
        (str(rec.get("factor_group")), str(rec.get("sub_variable")))
        for rec in sub_score_records
        if (
            (not allowed_groups or str(rec.get("factor_group")) in allowed_groups)
            and rec.get("factor_group")
            and rec.get("sub_variable")
        )
    }
    return len(observed_pairs)


def _missingness_factor_groups(config: Optional[Dict[str, Any]] = None) -> List[str]:
    """Resolve which factor groups count toward missingness.

    By default, missingness follows the required factor groups when configured.
    This keeps optional sparse groups such as sentiment/dividend from causing
    blanket data-quality failures while still allowing an explicit override.
    """
    cfg = (config or {}).get("risk_overlay", {})
    explicit_groups = [
        str(group).strip()
        for group in (cfg.get("missingness_factor_groups") or [])
        if str(group).strip()
    ]
    if explicit_groups:
        return explicit_groups

    required_groups = [
        str(group).strip()
        for group in (cfg.get("required_factor_groups") or [])
        if str(group).strip()
    ]
    if required_groups:
        return required_groups

    factor_cfg = (config or {}).get("factors", {})
    return [str(group).strip() for group in factor_cfg.keys() if str(group).strip()]


def apply_risk_overlay(
    factor_scores: List[Dict[str, Any]],
    risk_data: pd.DataFrame,
    sub_score_records: List[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Apply risk overlay filters and return per-symbol pass/fail results.

    :param factor_scores: Factor score records (one per symbol) with ``symbol`` key.
    :param risk_data: DataFrame with columns [symbol, log_market_cap, liquidity_20d, volatility_60d].
    :param sub_score_records: Sub-score records to assess data completeness.
    :param config: Optional config dict with ``risk_overlay`` section.
    :returns: List of risk overlay result dicts.
    """
    cfg = (config or {}).get("risk_overlay", {})
    min_log_mcap = _safe_float(cfg.get("min_market_cap_log", _DEFAULT_MIN_LOG_MARKET_CAP))
    min_liq = _safe_float(cfg.get("min_liquidity_20d", _DEFAULT_MIN_LIQUIDITY_20D))
    max_vol_pct = cfg.get("max_volatility_60d_percentile", _DEFAULT_MAX_VOL_PERCENTILE)
    max_missing = cfg.get("max_missing_factor_pct", _DEFAULT_MAX_MISSING_FACTOR_PCT)
    min_factor_groups = max(0, int(cfg.get("min_factor_groups_present", 0)))
    required_factor_groups = [
        str(group).strip()
        for group in (cfg.get("required_factor_groups") or [])
        if str(group).strip()
    ]
    missingness_factor_groups = _missingness_factor_groups(config=config)
    optional_blacklists = cfg.get("optional_percentile_blacklists") or []

    symbols = {r["symbol"] for r in factor_scores}

    # Build risk data lookup
    risk_lookup: Dict[str, Dict[str, Optional[float]]] = {}
    if not risk_data.empty:
        for _, row in risk_data.iterrows():
            sym = row.get("symbol")
            if sym in symbols:
                risk_lookup[sym] = {
                    "log_market_cap": _safe_float(row.get("log_market_cap")),
                    "liquidity_20d": _safe_float(row.get("liquidity_20d")),
                    "volatility_60d": _safe_float(row.get("volatility_60d")),
                }
                for blacklist in optional_blacklists:
                    column = str(blacklist.get("column") or "").strip()
                    if column:
                        risk_lookup[sym][column] = _safe_float(row.get(column))

    # Compute volatility cutoff from cross-sectional distribution
    all_vols = [
        v["volatility_60d"] for v in risk_lookup.values() if v["volatility_60d"] is not None
    ]
    vol_cutoff = None
    if all_vols:
        vol_cutoff = float(np.percentile(all_vols, max_vol_pct * 100))

    optional_cutoffs: Dict[str, float] = {}
    for blacklist in optional_blacklists:
        column = str(blacklist.get("column") or "").strip()
        percentile = float(blacklist.get("percentile", max_vol_pct))
        if not column:
            continue
        values = [
            metrics.get(column)
            for metrics in risk_lookup.values()
            if metrics.get(column) is not None
        ]
        if values:
            optional_cutoffs[column] = float(np.percentile(values, percentile * 100))

    # Compute missing factor % per symbol
    total_sub_vars = _expected_sub_variable_count(
        sub_score_records,
        config=config,
        factor_groups=missingness_factor_groups,
    )
    sub_counts: Dict[str, int] = {}
    for rec in sub_score_records:
        sym = rec.get("symbol")
        factor_group = str(rec.get("factor_group") or "").strip()
        if (
            sym
            and rec.get("z_score") is not None
            and (not missingness_factor_groups or factor_group in missingness_factor_groups)
        ):
            sub_counts[sym] = sub_counts.get(sym, 0) + 1

    factor_group_col_map = {
        "quality": "quality_score",
        "value": "value_score",
        "market_technical": "market_technical_score",
        "sentiment": "sentiment_score",
        "dividend": "dividend_score",
    }

    results: List[Dict[str, Any]] = []
    as_of_date = factor_scores[0]["as_of_date"] if factor_scores else None

    for sym in sorted(symbols):
        rd = risk_lookup.get(sym, {})
        mcap = rd.get("log_market_cap")
        liq = rd.get("liquidity_20d")
        vol = rd.get("volatility_60d")
        present_count = sub_counts.get(sym, 0)
        missing_pct = 1.0 - (present_count / total_sub_vars) if total_sub_vars > 0 else 1.0

        pass_mcap = True if min_log_mcap is None else (mcap is not None and mcap >= min_log_mcap)
        pass_liq = True if min_liq is None else (liq is not None and liq >= min_liq)
        pass_vol = True
        if vol_cutoff is not None and vol is not None:
            pass_vol = vol <= vol_cutoff
        pass_optional = True
        for column, cutoff in optional_cutoffs.items():
            value = rd.get(column)
            if value is not None and value > cutoff:
                pass_optional = False
                break

        factor_record = next((rec for rec in factor_scores if rec["symbol"] == sym), {})
        present_factor_groups = [
            group_name
            for group_name, col_name in factor_group_col_map.items()
            if _safe_float(factor_record.get(col_name)) is not None
        ]
        pass_group_count = len(present_factor_groups) >= min_factor_groups
        pass_required = all(group in present_factor_groups for group in required_factor_groups)
        pass_factor_coverage = pass_group_count and pass_required
        pass_data = (missing_pct <= max_missing) and pass_factor_coverage
        pass_all = pass_mcap and pass_liq and pass_vol and pass_optional and pass_data

        results.append(
            {
                "as_of_date": as_of_date,
                "symbol": sym,
                "log_market_cap": mcap,
                "liquidity_20d": liq,
                "volatility_60d": vol,
                "missing_factor_pct": round(missing_pct, 4),
                "factor_groups_present": len(present_factor_groups),
                "pass_market_cap": pass_mcap,
                "pass_liquidity": pass_liq,
                "pass_volatility": pass_vol,
                "pass_factor_coverage": pass_factor_coverage,
                "pass_data_quality": pass_data,
                "pass_all": pass_all,
            }
        )

    passed = sum(1 for r in results if r["pass_all"])
    failed = len(results) - passed
    logger.info(
        "risk_overlay: as_of=%s total=%d passed=%d failed=%d "
        "(mcap_thresh=%s liq_thresh=%s vol_cutoff=%s missing_thresh=%.0f%% required_groups=%s missingness_groups=%s optional_cutoffs=%s)",
        as_of_date,
        len(results),
        passed,
        failed,
        f"{min_log_mcap:.1f}" if min_log_mcap is not None else "disabled",
        f"{min_liq:.0f}" if min_liq is not None else "disabled",
        f"{vol_cutoff:.4f}" if vol_cutoff else "N/A",
        max_missing * 100,
        required_factor_groups or [],
        missingness_factor_groups or [],
        optional_cutoffs,
    )

    return results


def _safe_float(value: Any) -> Optional[float]:
    """Convert to finite float or None."""
    try:
        v = float(value)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None
