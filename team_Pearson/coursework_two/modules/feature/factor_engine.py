"""CW2 Factor Engine — compute first-level factor scores from CW1 atomic data.

Produces 5 first-level factors, each built from multiple sub-variables:

* **Quality**:  EBITDA Margin, ROE, Debt-to-Equity (inverted)
* **Value**:    Book-to-Price, Earnings-to-Price, EBITDA-to-EV
* **Market/Technical**: Momentum 1M, 6M, 12-1M
* **Sentiment**: 7D avg, 30D avg, Sentiment Surprise
* **Dividend**: Dividend Yield, Dividend Stability, Payout Sustainability

Each sub-variable is preprocessed (winsorize → industry-neutralize → Z-score)
before aggregation into first-level factor scores.

The engine reads from CW1's ``factor_observations`` and ``financial_observations``
tables and writes to CW2's ``feature_sub_scores`` and ``feature_factor_scores``.
CW1 stores the 12-1M momentum source as ``momentum_12m`` for legacy compatibility;
the upstream calculation already skips the latest 21 trading days, and CW2 maps
that source field to the explicit ``momentum_12_1m`` sub-variable name.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .preprocessing import preprocess_cross_section

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sub-variable definitions: map (factor_group, sub_variable) -> CW1 source
# ---------------------------------------------------------------------------

# CW1 factor_observations factor_names
_MARKET_FACTORS = {
    "momentum_1m",
    "momentum_6m",
    "momentum_3m",
    "momentum_12m",
    "volatility_20d",
    "volatility_60d",
    "beta_1y",
    "liquidity_20d",
    "log_market_cap",
    "dividend_yield",
    "dividend_stability",
    "payout_ratio",
    "pb_ratio",
    "debt_to_equity",
    "ebitda_margin",
    "ep_ratio",
    "ebitda_to_ev",
    "sentiment_7d_avg",
    "sentiment_30d_avg",
    "sentiment_surprise",
}

# CW1 financial_observations metric_names (for ROE)
_FINANCIAL_METRICS = {"net_income", "stockholders_equity", "roe"}

_DEFAULT_FACTOR_SUB_VARIABLES: Dict[str, List[str]] = {
    "quality": ["ebitda_margin", "roe", "debt_to_equity_inv"],
    "value": ["book_to_price", "earnings_to_price", "ebitda_to_ev"],
    "market_technical": ["momentum_1m", "momentum_6m", "momentum_12_1m"],
    "sentiment": ["sentiment_7d_avg", "sentiment_30d_avg", "sentiment_surprise"],
    "dividend": [
        "dividend_yield",
        "dividend_stability",
        "payout_sustainability",
    ],
}

# ---------------------------------------------------------------------------
# Sub-variable extractors
# ---------------------------------------------------------------------------


def _extract_sub_variables(
    factor_df: pd.DataFrame,
    financial_df: pd.DataFrame,
    as_of_date: date,
    sector_map: Dict[str, str],
) -> Dict[str, pd.DataFrame]:
    """Extract raw sub-variable values for each factor group on a rebalance date.

    Returns a dict keyed by factor_group, each containing a DataFrame with
    columns: [symbol, sub_variable, raw_value, gics_sector].

    The input ``factor_df`` may contain same-day records or mixed-frequency
    history. For each ``symbol × factor_name`` we keep the latest observation
    on or before ``as_of_date``. This lets slow-moving fundamentals, prior-close
    market data, and same-day sentiment coexist in one PIT-clean cross section.
    """
    results: Dict[str, List[Dict[str, Any]]] = {
        "quality": [],
        "value": [],
        "market_technical": [],
        "sentiment": [],
        "dividend": [],
    }

    # Keep the latest PIT-clean factor snapshot available on or before the
    # rebalance date for each symbol × factor_name pair.
    day = factor_df[factor_df["symbol"] != "_MACRO"].copy()
    if "observation_date" in day.columns:
        day = day[day["observation_date"] <= as_of_date].copy()
        if not day.empty:
            day = day.sort_values(["symbol", "factor_name", "observation_date"]).drop_duplicates(
                subset=["symbol", "factor_name"], keep="last"
            )
    if day.empty:
        return {
            k: pd.DataFrame(columns=["symbol", "sub_variable", "raw_value", "gics_sector"])
            for k in results
        }

    # Pivot to wide: one row per symbol, one column per factor_name
    pivot = day.pivot_table(
        index="symbol",
        columns="factor_name",
        values="factor_value",
        aggfunc="last",
    )

    def _add(group: str, sub_var: str, symbol: str, value: Optional[float]) -> None:
        if value is None or not np.isfinite(value):
            return
        results[group].append(
            {
                "symbol": symbol,
                "sub_variable": sub_var,
                "raw_value": value,
                "gics_sector": sector_map.get(symbol, "Unknown"),
            }
        )

    for symbol in pivot.index:
        row = pivot.loc[symbol]

        # --- Quality ---
        if "ebitda_margin" in row.index and pd.notna(row.get("ebitda_margin")):
            _add("quality", "ebitda_margin", symbol, float(row["ebitda_margin"]))
        # ROE: try CW1 precomputed, else compute from financial_observations
        roe_val = _get_roe(symbol, as_of_date, factor_df, financial_df)
        if roe_val is not None:
            _add("quality", "roe", symbol, roe_val)
        if "debt_to_equity" in row.index and pd.notna(row.get("debt_to_equity")):
            # Invert: lower D/E = higher quality
            de = float(row["debt_to_equity"])
            _add("quality", "debt_to_equity_inv", symbol, -de)

        # --- Value ---
        if "pb_ratio" in row.index and pd.notna(row.get("pb_ratio")):
            pb = float(row["pb_ratio"])
            if pb > 0:
                _add("value", "book_to_price", symbol, 1.0 / pb)
        if "ep_ratio" in row.index and pd.notna(row.get("ep_ratio")):
            _add("value", "earnings_to_price", symbol, float(row["ep_ratio"]))
        if "ebitda_to_ev" in row.index and pd.notna(row.get("ebitda_to_ev")):
            _add("value", "ebitda_to_ev", symbol, float(row["ebitda_to_ev"]))

        # --- Market/Technical ---
        if "momentum_1m" in row.index and pd.notna(row.get("momentum_1m")):
            _add("market_technical", "momentum_1m", symbol, float(row["momentum_1m"]))
        if "momentum_6m" in row.index and pd.notna(row.get("momentum_6m")):
            _add("market_technical", "momentum_6m", symbol, float(row["momentum_6m"]))
        # CW1 stores this as momentum_12m, but the value is already computed as
        # 12-1M momentum by skipping the most recent 21 trading days.
        if "momentum_12m" in row.index and pd.notna(row.get("momentum_12m")):
            _add("market_technical", "momentum_12_1m", symbol, float(row["momentum_12m"]))

        # --- Sentiment ---
        if "sentiment_7d_avg" in row.index and pd.notna(row.get("sentiment_7d_avg")):
            _add("sentiment", "sentiment_7d_avg", symbol, float(row["sentiment_7d_avg"]))
        if "sentiment_30d_avg" in row.index and pd.notna(row.get("sentiment_30d_avg")):
            _add(
                "sentiment",
                "sentiment_30d_avg",
                symbol,
                float(row["sentiment_30d_avg"]),
            )
        if "sentiment_surprise" in row.index and pd.notna(row.get("sentiment_surprise")):
            _add(
                "sentiment",
                "sentiment_surprise",
                symbol,
                float(row["sentiment_surprise"]),
            )

        # --- Dividend ---
        if "dividend_yield" in row.index and pd.notna(row.get("dividend_yield")):
            _add("dividend", "dividend_yield", symbol, float(row["dividend_yield"]))
        if "dividend_stability" in row.index and pd.notna(row.get("dividend_stability")):
            _add(
                "dividend",
                "dividend_stability",
                symbol,
                float(row["dividend_stability"]),
            )
        if "payout_ratio" in row.index and pd.notna(row.get("payout_ratio")):
            pr = float(row["payout_ratio"])
            # Convert payout ratio into a positive-oriented sustainability input.
            # We treat the raw "bad" variable as unsustainable payout pressure.
            # Low positive payout ratios are not penalized: yield already
            # captures shareholder cash return, while sustainability should
            # mainly punish distributions that look uncovered or too stretched.
            if pr <= 0.0:
                badness = 1.0 + abs(pr)
            elif pr <= 0.80:
                badness = 0.0
            elif pr <= 1.00:
                badness = pr - 0.80
            else:
                badness = 0.20 + (pr - 1.00) * 2.0
            _add("dividend", "payout_sustainability", symbol, -badness)

    return {
        k: (
            pd.DataFrame(v)
            if v
            else pd.DataFrame(columns=["symbol", "sub_variable", "raw_value", "gics_sector"])
        )
        for k, v in results.items()
    }


def _get_roe(
    symbol: str,
    as_of_date: date,
    factor_df: pd.DataFrame,
    financial_df: pd.DataFrame,
) -> Optional[float]:
    """Get ROE for a symbol, preferring CW1 precomputed value."""
    # Try EDGAR-derived ROE from financial_observations
    if not financial_df.empty:
        roe_rows = financial_df[
            (financial_df["symbol"] == symbol)
            & (financial_df["metric_name"] == "roe")
            & (financial_df["report_date"] <= as_of_date)
        ]
        if "publish_date" in roe_rows.columns:
            roe_rows = roe_rows[roe_rows["publish_date"] <= as_of_date]
        if not roe_rows.empty:
            val = roe_rows.sort_values("report_date").iloc[-1]["metric_value"]
            try:
                v = float(val)
                return v if np.isfinite(v) else None
            except (TypeError, ValueError):
                pass

    # Fallback: compute from net_income / stockholders_equity
    # Prefer same-source pairs; relax to mixed-source when that is the only
    # PIT-valid way to recover coverage.
    if not financial_df.empty:
        ni = financial_df[
            (financial_df["symbol"] == symbol)
            & (financial_df["metric_name"] == "net_income")
            & (financial_df["report_date"] <= as_of_date)
        ]
        eq = financial_df[
            (financial_df["symbol"] == symbol)
            & (financial_df["metric_name"] == "stockholders_equity")
            & (financial_df["report_date"] <= as_of_date)
        ]
        if "publish_date" in ni.columns:
            ni = ni[ni["publish_date"] <= as_of_date]
        if "publish_date" in eq.columns:
            eq = eq[eq["publish_date"] <= as_of_date]
        if not ni.empty and not eq.empty:
            ni = ni.copy()
            eq = eq.copy()
            if "source" in ni.columns:
                ni["source"] = ni["source"].astype(str).str.strip()
            else:
                ni["source"] = ""
            if "source" in eq.columns:
                eq["source"] = eq["source"].astype(str).str.strip()
            else:
                eq["source"] = ""

            ni_same = ni[ni["source"] != ""]
            eq_same = eq[eq["source"] != ""]

            if not ni_same.empty and not eq_same.empty:
                exact = ni_same.merge(
                    eq_same,
                    on=["symbol", "report_date", "source", "publish_date"],
                    suffixes=("_ni", "_eq"),
                    how="inner",
                )
                if not exact.empty:
                    row = exact.sort_values(["report_date", "publish_date"]).iloc[-1]
                    ni_val = float(row["metric_value_ni"])
                    eq_val = float(row["metric_value_eq"])
                    if eq_val > 0 and np.isfinite(ni_val) and np.isfinite(eq_val):
                        return ni_val / eq_val

                same_report = ni_same.merge(
                    eq_same,
                    on=["symbol", "report_date", "source"],
                    suffixes=("_ni", "_eq"),
                    how="inner",
                )
                if not same_report.empty:
                    same_report["_pair_publish_date"] = same_report[
                        ["publish_date_ni", "publish_date_eq"]
                    ].max(axis=1)
                    row = same_report.sort_values(["report_date", "_pair_publish_date"]).iloc[-1]
                    ni_val = float(row["metric_value_ni"])
                    eq_val = float(row["metric_value_eq"])
                    if eq_val > 0 and np.isfinite(ni_val) and np.isfinite(eq_val):
                        return ni_val / eq_val

            mixed_same_report = ni.merge(
                eq,
                on=["symbol", "report_date"],
                suffixes=("_ni", "_eq"),
                how="inner",
            )
            if not mixed_same_report.empty:
                mixed_same_report["_pair_publish_date"] = mixed_same_report[
                    ["publish_date_ni", "publish_date_eq"]
                ].max(axis=1)
                row = mixed_same_report.sort_values(["report_date", "_pair_publish_date"]).iloc[-1]
                ni_val = float(row["metric_value_ni"])
                eq_val = float(row["metric_value_eq"])
                if eq_val > 0 and np.isfinite(ni_val) and np.isfinite(eq_val):
                    logger.info(
                        "pair_integrity_relaxed=True factor=roe symbol=%s pair_mode=%s left_source=%s right_source=%s",
                        symbol,
                        "mixed_source_same_report",
                        str(row.get("source_ni") or "").strip() or "unknown",
                        str(row.get("source_eq") or "").strip() or "unknown",
                    )
                    return ni_val / eq_val

            ni_latest = ni.sort_values(["report_date", "publish_date"]).iloc[-1]
            eq_latest = eq.sort_values(["report_date", "publish_date"]).iloc[-1]
            ni_val = float(ni_latest["metric_value"])
            eq_val = float(eq_latest["metric_value"])
            if eq_val > 0 and np.isfinite(ni_val) and np.isfinite(eq_val):
                logger.info(
                    "pair_integrity_relaxed=True factor=roe symbol=%s pair_mode=%s left_source=%s right_source=%s",
                    symbol,
                    "mixed_source_latest",
                    str(ni_latest.get("source") or "").strip() or "unknown",
                    str(eq_latest.get("source") or "").strip() or "unknown",
                )
                return ni_val / eq_val

    return None


# ---------------------------------------------------------------------------
# First-level factor aggregation
# ---------------------------------------------------------------------------


def compute_factor_scores_for_date(
    factor_df: pd.DataFrame,
    financial_df: pd.DataFrame,
    as_of_date: date,
    sector_map: Dict[str, str],
    config: Optional[Dict[str, Any]] = None,
    regime: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Compute all first-level factor scores for a single cross-sectional date.

    :param factor_df: CW1 factor_observations data (multi-date, filtered by caller).
    :param financial_df: CW1 financial_observations data.
    :param as_of_date: The date to compute scores for.
    :param sector_map: Dict mapping symbol -> gics_sector.
    :param config: Optional config dict (preprocessing params).
    :param regime: Optional ``normal``/``stress`` override for regime-aware
        sub-signal weighting during first-level factor aggregation.
    :returns: Tuple of (sub_score_records, factor_score_records).
    """
    cfg = config or {}
    preprocess_cfg = cfg.get("preprocessing", {})
    lower_pct = preprocess_cfg.get("winsorize_percentile", 0.025)
    upper_pct = 1.0 - lower_pct
    group_col = preprocess_cfg.get("neutralize_by", "gics_sector")
    min_observations = int(preprocess_cfg.get("min_observations", 2))
    factor_specs = _resolve_factor_group_specs(cfg, regime=regime)
    # Extract raw sub-variables
    sub_vars = _extract_sub_variables(factor_df, financial_df, as_of_date, sector_map)

    sub_score_records: List[Dict[str, Any]] = []

    for factor_group, raw_df in sub_vars.items():
        group_spec = factor_specs.get(factor_group, {})
        enabled_sub_variables = set(group_spec.get("sub_variables") or [])
        if enabled_sub_variables:
            raw_df = raw_df[raw_df["sub_variable"].isin(enabled_sub_variables)].copy()
        if raw_df.empty:
            continue

        for sub_var_name, sub_df in raw_df.groupby("sub_variable"):
            if len(sub_df) < 2:
                # Not enough data for cross-sectional stats
                for _, row in sub_df.iterrows():
                    sub_score_records.append(
                        {
                            "as_of_date": as_of_date.isoformat(),
                            "symbol": row["symbol"],
                            "factor_group": factor_group,
                            "sub_variable": sub_var_name,
                            "raw_value": row["raw_value"],
                            "winsorized_value": None,
                            "neutralized_value": None,
                            "z_score": None,
                            "gics_sector": row.get("gics_sector"),
                        }
                    )
                continue

            processed = preprocess_cross_section(
                sub_df,
                value_col="raw_value",
                group_col=group_col,
                lower_pct=lower_pct,
                upper_pct=upper_pct,
                min_observations=min_observations,
            )

            for _, row in processed.iterrows():
                sym = row["symbol"]
                z = row.get("z_score")
                if z is not None and not np.isfinite(z):
                    z = None

                sub_score_records.append(
                    {
                        "as_of_date": as_of_date.isoformat(),
                        "symbol": sym,
                        "factor_group": factor_group,
                        "sub_variable": sub_var_name,
                        "raw_value": row["raw_value"],
                        "winsorized_value": row.get("winsorized_value"),
                        "neutralized_value": row.get("neutralized_value"),
                        "z_score": z,
                        "gics_sector": row.get("gics_sector"),
                    }
                )
    factor_score_records = aggregate_factor_scores_from_sub_records(
        sub_score_records,
        config=cfg,
        regime=regime,
    )
    return sub_score_records, factor_score_records


def aggregate_factor_scores_from_sub_records(
    sub_score_records: List[Dict[str, Any]],
    *,
    config: Optional[Dict[str, Any]] = None,
    regime: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Aggregate sub-score records into first-level factor scores."""
    factor_specs = _resolve_factor_group_specs(config, regime=regime)
    symbol_zscores: Dict[str, Dict[str, Dict[str, float]]] = {}
    symbol_dates: Dict[str, Any] = {}

    for record in sub_score_records:
        symbol = str(record.get("symbol") or "").strip()
        factor_group = str(record.get("factor_group") or "").strip()
        sub_variable = str(record.get("sub_variable") or "").strip()
        if not symbol or factor_group not in factor_specs:
            continue
        enabled_sub_variables = set(factor_specs.get(factor_group, {}).get("sub_variables") or [])
        if enabled_sub_variables and sub_variable not in enabled_sub_variables:
            continue
        symbol_dates.setdefault(symbol, record.get("as_of_date"))
        try:
            z_score = float(record.get("z_score"))
        except (TypeError, ValueError):
            z_score = None
        if z_score is None or not np.isfinite(z_score):
            continue
        symbol_zscores.setdefault(symbol, {}).setdefault(factor_group, {})[sub_variable] = z_score

    factor_score_records: List[Dict[str, Any]] = []
    for symbol in sorted(symbol_zscores):
        scores: Dict[str, Optional[float]] = {}
        for fg in ["quality", "value", "market_technical", "sentiment", "dividend"]:
            sub_z = symbol_zscores.get(symbol, {}).get(fg, {})
            if sub_z:
                scores[fg] = _weighted_sub_score(
                    sub_z,
                    factor_specs.get(fg, {}).get("weights"),
                )
            else:
                scores[fg] = None

        factor_score_records.append(
            {
                "as_of_date": _serialize_as_of_date(symbol_dates.get(symbol)),
                "symbol": symbol,
                "quality_score": scores.get("quality"),
                "value_score": scores.get("value"),
                "market_technical_score": scores.get("market_technical"),
                "sentiment_score": scores.get("sentiment"),
                "dividend_score": scores.get("dividend"),
            }
        )
    return factor_score_records


def _serialize_as_of_date(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except TypeError:
            return value
    return value


def _resolve_factor_group_specs(
    config: Optional[Dict[str, Any]],
    *,
    regime: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    factors_cfg = (config or {}).get("factors", {})
    resolved: Dict[str, Dict[str, Any]] = {}
    for factor_group, default_sub_variables in _DEFAULT_FACTOR_SUB_VARIABLES.items():
        raw_group_cfg = dict((factors_cfg or {}).get(factor_group) or {})
        configured_sub_variables = raw_group_cfg.get("sub_variables") or list(default_sub_variables)
        sub_variables: List[str] = []
        for name in configured_sub_variables:
            sub_name = str(name)
            if sub_name in default_sub_variables and sub_name not in sub_variables:
                sub_variables.append(sub_name)
        if not sub_variables:
            sub_variables = list(default_sub_variables)
        weight_source = raw_group_cfg.get("weights", "equal")
        raw_regime_weights = raw_group_cfg.get("regime_weights") or {}
        if regime in {"normal", "stress"} and isinstance(raw_regime_weights, dict):
            regime_specific = raw_regime_weights.get(regime)
            if regime_specific is not None:
                weight_source = regime_specific
        resolved[factor_group] = {
            "sub_variables": sub_variables,
            "weights": _resolve_sub_variable_weights(
                factor_group=factor_group,
                sub_variables=sub_variables,
                raw_weights=weight_source,
            ),
        }
    return resolved


def _resolve_sub_variable_weights(
    *,
    factor_group: str,
    sub_variables: List[str],
    raw_weights: Any,
) -> Dict[str, float]:
    if isinstance(raw_weights, str):
        if raw_weights.strip().lower() != "equal":
            raise ValueError(
                f"Unsupported weight mode for factor_group={factor_group}: {raw_weights}"
            )
        return {name: 1.0 for name in sub_variables}
    if not isinstance(raw_weights, dict):
        raise ValueError(f"factor_group={factor_group} weights must be 'equal' or a dict")

    weights: Dict[str, float] = {}
    for name in sub_variables:
        value = float(raw_weights.get(name, 0.0))
        if value < 0.0:
            raise ValueError(f"factor_group={factor_group} weight cannot be negative: {name}")
        weights[name] = value
    if sum(weights.values()) <= 0.0:
        raise ValueError(
            f"factor_group={factor_group} weight dict must contain positive total weight"
        )
    return weights


def _weighted_sub_score(
    sub_scores: Dict[str, float],
    weight_map: Optional[Dict[str, float]],
) -> Optional[float]:
    if not sub_scores:
        return None
    weights = weight_map or {name: 1.0 for name in sub_scores}
    weighted_sum = 0.0
    total_weight = 0.0
    for name, score in sub_scores.items():
        weight = float(weights.get(name, 0.0))
        if weight <= 0.0:
            continue
        weighted_sum += weight * float(score)
        total_weight += weight
    if total_weight <= 0.0:
        return None
    return weighted_sum / total_weight
