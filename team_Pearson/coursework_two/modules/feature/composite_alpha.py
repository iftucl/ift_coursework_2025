"""Composite alpha score computation with VIX-triggered regime switching.

Combines the 5 first-level factor scores into a single composite alpha
using regime-dependent weights:

* **Normal regime** (VIX < threshold):
  Quality 20%, Value 20%, Market/Technical 30%, Sentiment 20%, Dividend 10%

* **Stress regime** (VIX >= threshold):
  Quality 30%, Value 20%, Market/Technical 10%, Sentiment 10%, Dividend 30%

The VIX threshold and weights are configurable via ``config/conf.yaml``.
For more stable allocation, the regime engine also supports optional
hysteresis with separate entry/exit thresholds and persistence windows.
"""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_FACTOR_COLUMN_MAP = {
    "quality": "quality_score",
    "value": "value_score",
    "market_technical": "market_technical_score",
    "sentiment": "sentiment_score",
    "dividend": "dividend_score",
}
_IC_WEIGHT_CACHE: Dict[Tuple[Any, ...], Dict[str, float]] = {}

# Default regime weights (overridden by config)
_DEFAULT_NORMAL_WEIGHTS = {
    "quality": 0.20,
    "value": 0.20,
    "market_technical": 0.30,
    "sentiment": 0.20,
    "dividend": 0.10,
}

_DEFAULT_STRESS_WEIGHTS = {
    "quality": 0.30,
    "value": 0.20,
    "market_technical": 0.10,
    "sentiment": 0.10,
    "dividend": 0.30,
}

_DEFAULT_VIX_THRESHOLD = 25.0
_DEFAULT_VIX_EXIT_THRESHOLD = 22.0
_DEFAULT_REGIME_MODE = "threshold"
_DEFAULT_PERSISTENCE = 1


def determine_regime(
    vix_level: Optional[float],
    threshold: float = _DEFAULT_VIX_THRESHOLD,
    *,
    vix_history: Optional[Iterable[float]] = None,
    macro_context: Optional[Dict[str, Any]] = None,
    signal_model: str = "vix_only",
    vix_warning_threshold: Optional[float] = None,
    term_spread_stress_threshold: float = 0.0,
    term_spread_confirm_days: int = 1,
    mode: str = _DEFAULT_REGIME_MODE,
    exit_threshold: Optional[float] = None,
    stress_persistence: int = _DEFAULT_PERSISTENCE,
    normal_persistence: int = _DEFAULT_PERSISTENCE,
) -> str:
    """Determine market regime based on VIX level.

    :param vix_level: Current VIX close value.
    :param threshold: VIX level at or above which stress regime activates.
    :param vix_history: Optional ordered VIX history up to the current date.
    :param mode: ``threshold`` for simple switching, ``hysteresis`` for
        asymmetric entry/exit rules with persistence.
    :param exit_threshold: VIX level below which stress can exit when using
        hysteresis. Defaults to the stress threshold when omitted.
    :param stress_persistence: Required consecutive observations at or above the
        stress threshold before entering stress regime.
    :param normal_persistence: Required consecutive observations below the exit
        threshold before reverting to normal regime.
    :returns: ``'stress'`` if VIX >= threshold, else ``'normal'``.
    """
    base_regime = _determine_vix_regime(
        vix_level,
        threshold=threshold,
        vix_history=vix_history,
        mode=mode,
        exit_threshold=exit_threshold,
        stress_persistence=stress_persistence,
        normal_persistence=normal_persistence,
    )
    model = str(signal_model or "vix_only").strip().lower()
    if model == "vix_only":
        return base_regime
    if model != "vix_term_spread":
        raise ValueError(f"Unsupported regime signal_model: {signal_model}")

    if base_regime == "stress":
        return "stress"

    term_spread_level = _safe_finite(
        (macro_context or {}).get("term_spread_level") if isinstance(macro_context, dict) else None
    )
    if term_spread_level is None:
        return base_regime

    warning_threshold = float(
        vix_warning_threshold
        if vix_warning_threshold is not None
        else max(0.0, float(threshold) - 5.0)
    )
    vix_hist = _normalized_vix_history(vix_history, fallback=vix_level)
    spread_hist = _normalized_numeric_history(
        (
            (macro_context or {}).get("term_spread_history")
            if isinstance(macro_context, dict)
            else None
        ),
        fallback=term_spread_level,
    )
    if _tail_combo_stress(
        vix_hist,
        spread_hist,
        vix_warning_threshold=warning_threshold,
        term_spread_stress_threshold=float(term_spread_stress_threshold),
        required=max(1, int(term_spread_confirm_days)),
    ):
        return "stress"
    return base_regime


def compute_composite_alpha(
    factor_scores: List[Dict[str, Any]],
    vix_level: Optional[float],
    config: Optional[Dict[str, Any]] = None,
    vix_history: Optional[Iterable[float]] = None,
    macro_context: Optional[Dict[str, Any]] = None,
    forced_regime: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Compute composite alpha score for each symbol using regime-based weights.

    :param factor_scores: List of dicts with keys:
        ``as_of_date``, ``symbol``, ``quality_score``, ``value_score``,
        ``market_technical_score``, ``sentiment_score``, ``dividend_score``.
    :param vix_level: Current VIX close for regime determination.
    :param config: Optional config dict with ``regime`` section.
    :param vix_history: Optional ordered VIX history used for hysteresis.
    :returns: Updated factor_scores with ``composite_alpha``, ``regime``, ``vix_level`` added.
    """
    cfg = (config or {}).get("regime", {})
    threshold = float(cfg.get("vix_stress_threshold", _DEFAULT_VIX_THRESHOLD))
    signal_model = str(cfg.get("signal_model", "vix_only")).strip().lower()
    regime_mode = str(cfg.get("mode") or _DEFAULT_REGIME_MODE).strip().lower()
    regime = resolve_regime_from_config(
        vix_level=vix_level,
        config=config,
        vix_history=vix_history,
        macro_context=macro_context,
        forced_regime=forced_regime,
    )

    weights = _resolve_composite_weights(
        factor_scores=factor_scores,
        regime=regime,
        config=config,
    )

    for record in factor_scores:
        alpha = 0.0
        available_weight = 0.0

        for factor_key, col_name in _FACTOR_COLUMN_MAP.items():
            score = record.get(col_name)
            w = weights.get(factor_key, 0.0)
            try:
                numeric_score = float(score) if score is not None else None
            except (TypeError, ValueError):
                numeric_score = None
            if numeric_score is not None and np.isfinite(numeric_score):
                alpha += w * numeric_score
                available_weight += w

        # Re-scale if some factors are missing
        if available_weight > 0 and available_weight < 0.99:
            alpha = alpha / available_weight
        elif available_weight == 0:
            alpha = None

        record["composite_alpha"] = alpha
        record["regime"] = regime
        record["vix_level"] = vix_level

    logger.info(
        "composite_alpha: regime=%s vix=%.2f threshold=%.1f mode=%s symbols=%d weights=%s",
        regime,
        vix_level if vix_level is not None else 0.0,
        threshold,
        f"{signal_model}:{regime_mode}",
        len(factor_scores),
        {k: round(v, 2) for k, v in weights.items()},
    )

    return factor_scores


def _resolve_composite_weights(
    *,
    factor_scores: List[Dict[str, Any]],
    regime: str,
    config: Optional[Dict[str, Any]],
) -> Dict[str, float]:
    cfg = (config or {}).get("regime", {})
    base_weights = _normalized_weights(
        (
            {**_DEFAULT_STRESS_WEIGHTS, **cfg.get("stress", {})}
            if regime == "stress"
            else {**_DEFAULT_NORMAL_WEIGHTS, **cfg.get("normal", {})}
        )
    )
    ic_cfg = cfg.get("ic_weighting") or {}
    if not bool(ic_cfg.get("enabled")):
        return base_weights

    as_of_date = _extract_as_of_date(factor_scores)
    if as_of_date is None:
        logger.warning(
            "composite_alpha: ic_weighting enabled but factor_scores had no usable as_of_date; falling back to regime prior"
        )
        return base_weights

    cache_key = (
        as_of_date.isoformat(),
        regime,
        int(ic_cfg.get("lookback_months", 36)),
        int(ic_cfg.get("min_history_months", 12)),
        int(ic_cfg.get("min_cross_section", 25)),
        str(ic_cfg.get("ic_method", "spearman")).strip().lower(),
        str(ic_cfg.get("score_metric", "ic_ir")).strip().lower(),
        float(ic_cfg.get("prior_mix", 0.50)),
        float(ic_cfg.get("score_clip", 2.0)),
        bool(ic_cfg.get("positive_only", True)),
        bool(ic_cfg.get("regime_split", False)),
    )
    cached = _IC_WEIGHT_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)

    try:
        weights = _compute_ic_weighted_factor_weights(
            as_of_date=as_of_date,
            regime=regime,
            base_weights=base_weights,
            ic_cfg=ic_cfg,
        )
    except Exception as exc:
        logger.warning(
            "composite_alpha: ic_weighting failed for as_of=%s regime=%s; falling back to regime prior (%s)",
            as_of_date,
            regime,
            exc,
        )
        weights = base_weights

    _IC_WEIGHT_CACHE[cache_key] = dict(weights)
    return weights


def _compute_ic_weighted_factor_weights(
    *,
    as_of_date: date,
    regime: str,
    base_weights: Dict[str, float],
    ic_cfg: Dict[str, Any],
) -> Dict[str, float]:
    history = _load_factor_ic_history(
        as_of_date=as_of_date,
        regime=regime,
        lookback_months=max(1, int(ic_cfg.get("lookback_months", 36))),
        min_cross_section=max(3, int(ic_cfg.get("min_cross_section", 25))),
        ic_method=str(ic_cfg.get("ic_method", "spearman")).strip().lower(),
        regime_split=bool(ic_cfg.get("regime_split", False)),
    )
    min_history = max(1, int(ic_cfg.get("min_history_months", 12)))
    if not history or max((len(v) for v in history.values()), default=0) < min_history:
        logger.info(
            "composite_alpha: ic_weighting skipped for as_of=%s due to insufficient history",
            as_of_date,
        )
        return base_weights

    score_metric = str(ic_cfg.get("score_metric", "ic_ir")).strip().lower()
    score_clip = float(ic_cfg.get("score_clip", 2.0))
    positive_only = bool(ic_cfg.get("positive_only", True))
    prior_mix = float(ic_cfg.get("prior_mix", 0.50))
    prior_mix = min(1.0, max(0.0, prior_mix))
    lookback_months = max(1, int(ic_cfg.get("lookback_months", 36)))

    raw_scores: Dict[str, float] = {}
    diagnostics: Dict[str, Dict[str, float]] = {}
    for factor_name in _FACTOR_COLUMN_MAP:
        ic_series = [float(v) for v in history.get(factor_name, []) if np.isfinite(v)]
        if len(ic_series) < min_history:
            diagnostics[factor_name] = {
                "obs": float(len(ic_series)),
                "mean_ic": 0.0,
                "ic_ir": 0.0,
                "raw_score": 0.0,
            }
            raw_scores[factor_name] = 0.0
            continue
        mean_ic = float(np.mean(ic_series))
        if len(ic_series) >= 2:
            std_ic = float(np.std(ic_series, ddof=1))
        else:
            std_ic = 0.0
        if score_metric == "ic_mean":
            raw_score = mean_ic
        else:
            raw_score = mean_ic / max(std_ic, 1.0e-6)
        raw_score *= math.sqrt(min(1.0, len(ic_series) / lookback_months))
        raw_score = max(-score_clip, min(score_clip, raw_score))
        if positive_only:
            raw_score = max(0.0, raw_score)
        raw_scores[factor_name] = raw_score
        diagnostics[factor_name] = {
            "obs": float(len(ic_series)),
            "mean_ic": mean_ic,
            "ic_ir": (mean_ic / std_ic) if std_ic > 0.0 else 0.0,
            "raw_score": raw_score,
        }

    total_raw = float(sum(raw_scores.values()))
    if total_raw <= 0.0:
        logger.info(
            "composite_alpha: ic_weighting produced no positive signal for as_of=%s; using regime prior",
            as_of_date,
        )
        return base_weights

    signal_weights = {
        factor_name: raw_scores[factor_name] / total_raw for factor_name in raw_scores
    }
    blended = {
        factor_name: prior_mix * base_weights.get(factor_name, 0.0)
        + (1.0 - prior_mix) * signal_weights.get(factor_name, 0.0)
        for factor_name in _FACTOR_COLUMN_MAP
    }
    final_weights = _normalized_weights(blended)
    logger.info(
        "composite_alpha: ic_weighting active as_of=%s regime=%s prior_mix=%.2f score_metric=%s weights=%s diagnostics=%s",
        as_of_date,
        regime,
        prior_mix,
        score_metric,
        {k: round(v, 3) for k, v in final_weights.items()},
        {
            k: {
                "obs": int(v["obs"]),
                "mean_ic": round(v["mean_ic"], 4),
                "ic_ir": round(v["ic_ir"], 4),
                "raw": round(v["raw_score"], 4),
            }
            for k, v in diagnostics.items()
        },
    )
    return final_weights


def _load_factor_ic_history(
    *,
    as_of_date: date,
    regime: str,
    lookback_months: int,
    min_cross_section: int,
    ic_method: str,
    regime_split: bool,
) -> Dict[str, List[float]]:
    import pandas as pd
    from sqlalchemy import text
    from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine

    engine = get_db_engine()
    safe_method = "spearman" if ic_method == "spearman" else "pearson"

    dates_sql = f"""
        SELECT DISTINCT as_of_date
        FROM systematic_equity.feature_factor_scores
        WHERE as_of_date < :as_of_date
        {"AND regime = :regime" if regime_split else ""}
        ORDER BY as_of_date DESC
        LIMIT :limit
    """
    with engine.connect() as conn:
        params = {"as_of_date": as_of_date, "limit": int(lookback_months)}
        if regime_split:
            params["regime"] = regime
        hist_dates = [
            row[0] for row in conn.execute(text(dates_sql), params).fetchall() if row[0] is not None
        ]
    hist_dates = sorted(hist_dates)
    if not hist_dates:
        return {}

    eval_dates = hist_dates + [as_of_date]
    with engine.connect() as conn:
        factor_df = pd.DataFrame(
            conn.execute(
                text("""
                    SELECT as_of_date, symbol, quality_score, value_score,
                           market_technical_score, sentiment_score, dividend_score
                    FROM systematic_equity.feature_factor_scores
                    WHERE as_of_date = ANY(:dates)
                    """),
                {"dates": hist_dates},
            )
            .mappings()
            .all()
        )
        price_df = pd.DataFrame(
            conn.execute(
                text("""
                    SELECT symbol, observation_date, factor_value
                    FROM systematic_equity.factor_observations
                    WHERE factor_name = 'adjusted_close_price'
                      AND symbol = ANY(:symbols)
                      AND observation_date BETWEEN :start_date AND :end_date
                    """),
                {
                    "symbols": (
                        sorted(factor_df["symbol"].astype(str).unique())
                        if not factor_df.empty
                        else []
                    ),
                    "start_date": min(eval_dates),
                    "end_date": max(eval_dates),
                },
            )
            .mappings()
            .all()
        )

    if factor_df.empty or price_df.empty:
        return {}

    factor_df["as_of_date"] = pd.to_datetime(factor_df["as_of_date"], errors="coerce").dt.date
    factor_df["symbol"] = factor_df["symbol"].astype(str)

    price_df["observation_date"] = pd.to_datetime(
        price_df["observation_date"], errors="coerce"
    ).dt.date
    price_df["symbol"] = price_df["symbol"].astype(str)
    price_df["factor_value"] = pd.to_numeric(price_df["factor_value"], errors="coerce")
    price_panel = (
        price_df.pivot_table(
            index="observation_date",
            columns="symbol",
            values="factor_value",
            aggfunc="last",
        )
        .sort_index()
        .reindex(eval_dates)
    )
    forward_returns = price_panel.shift(-1).divide(price_panel).subtract(1.0)

    ic_history: Dict[str, List[float]] = {name: [] for name in _FACTOR_COLUMN_MAP}
    for start_date in hist_dates:
        scores_for_date = factor_df[factor_df["as_of_date"] == start_date].copy()
        if scores_for_date.empty:
            continue
        returns_row = (
            forward_returns.loc[start_date] if start_date in forward_returns.index else None
        )
        if returns_row is None:
            continue
        returns_series = returns_row.dropna()
        if returns_series.empty:
            continue
        returns_frame = (
            returns_series.rename("forward_return")
            .reset_index()
            .rename(columns={"index": "symbol"})
        )
        returns_frame["symbol"] = returns_frame["symbol"].astype(str)

        for factor_name, score_col in _FACTOR_COLUMN_MAP.items():
            merged = scores_for_date[["symbol", score_col]].merge(
                returns_frame,
                on="symbol",
                how="inner",
            )
            merged[score_col] = pd.to_numeric(merged[score_col], errors="coerce")
            merged["forward_return"] = pd.to_numeric(merged["forward_return"], errors="coerce")
            merged = merged.dropna(subset=[score_col, "forward_return"])
            if len(merged) < min_cross_section:
                continue
            if merged[score_col].nunique() < 2 or merged["forward_return"].nunique() < 2:
                continue
            if safe_method == "spearman":
                ic_value = float(
                    merged[score_col]
                    .rank(method="average")
                    .corr(
                        merged["forward_return"].rank(method="average"),
                        method="pearson",
                    )
                )
            else:
                ic_value = float(merged[score_col].corr(merged["forward_return"], method="pearson"))
            if np.isfinite(ic_value):
                ic_history[factor_name].append(ic_value)
    return ic_history


def _extract_as_of_date(factor_scores: List[Dict[str, Any]]) -> Optional[date]:
    dates = sorted(
        {
            parsed
            for row in factor_scores
            for parsed in [_coerce_date(row.get("as_of_date"))]
            if parsed is not None
        }
    )
    if not dates:
        return None
    return dates[-1]


def _coerce_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _normalized_weights(weights: Dict[str, float]) -> Dict[str, float]:
    clean = {
        factor_name: max(0.0, float(weights.get(factor_name, 0.0)))
        for factor_name in _FACTOR_COLUMN_MAP
    }
    total = float(sum(clean.values()))
    if total <= 0.0:
        equal = 1.0 / len(_FACTOR_COLUMN_MAP)
        return {factor_name: equal for factor_name in _FACTOR_COLUMN_MAP}
    return {factor_name: value / total for factor_name, value in clean.items()}


def resolve_regime_from_config(
    *,
    vix_level: Optional[float],
    config: Optional[Dict[str, Any]] = None,
    vix_history: Optional[Iterable[float]] = None,
    macro_context: Optional[Dict[str, Any]] = None,
    forced_regime: Optional[str] = None,
) -> str:
    """Resolve the active regime from CW2 config plus macro inputs."""
    cfg = (config or {}).get("regime", {})
    threshold = float(cfg.get("vix_stress_threshold", _DEFAULT_VIX_THRESHOLD))
    signal_model = str(cfg.get("signal_model", "vix_only")).strip().lower()
    regime_mode = str(cfg.get("mode") or _DEFAULT_REGIME_MODE).strip().lower()
    exit_threshold = cfg.get("vix_exit_threshold", _DEFAULT_VIX_EXIT_THRESHOLD)
    stress_persistence = int(cfg.get("stress_persistence", _DEFAULT_PERSISTENCE))
    normal_persistence = int(cfg.get("normal_persistence", _DEFAULT_PERSISTENCE))
    vix_warning_threshold = cfg.get("vix_warning_threshold")
    term_spread_stress_threshold = float(cfg.get("term_spread_stress_threshold", 0.0))
    term_spread_confirm_days = int(cfg.get("term_spread_confirm_days", 1))
    if forced_regime is not None:
        return _normalize_forced_regime(forced_regime)
    return determine_regime(
        vix_level,
        threshold,
        vix_history=vix_history,
        macro_context=macro_context,
        signal_model=signal_model,
        vix_warning_threshold=vix_warning_threshold,
        term_spread_stress_threshold=term_spread_stress_threshold,
        term_spread_confirm_days=term_spread_confirm_days,
        mode=regime_mode,
        exit_threshold=exit_threshold,
        stress_persistence=stress_persistence,
        normal_persistence=normal_persistence,
    )


def _normalize_forced_regime(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text not in {"normal", "stress"}:
        raise ValueError(f"Unsupported forced regime: {value}")
    return text


def _normalized_vix_history(
    values: Optional[Iterable[float]],
    *,
    fallback: Optional[float],
) -> List[float]:
    out: List[float] = []
    if values is not None:
        for value in values:
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(parsed):
                out.append(parsed)
    if out:
        return out
    if fallback is None or not np.isfinite(fallback):
        return []
    return [float(fallback)]


def _normalized_numeric_history(
    values: Optional[Iterable[float]],
    *,
    fallback: Optional[float],
) -> List[float]:
    out: List[float] = []
    if values is not None:
        for value in values:
            parsed = _safe_finite(value)
            if parsed is not None:
                out.append(parsed)
    if out:
        return out
    parsed_fallback = _safe_finite(fallback)
    if parsed_fallback is None:
        return []
    return [parsed_fallback]


def _determine_vix_regime(
    vix_level: Optional[float],
    *,
    threshold: float,
    vix_history: Optional[Iterable[float]],
    mode: str,
    exit_threshold: Optional[float],
    stress_persistence: int,
    normal_persistence: int,
) -> str:
    if vix_level is None or not np.isfinite(vix_level):
        return "normal"

    regime_mode = str(mode or _DEFAULT_REGIME_MODE).strip().lower()
    if regime_mode == "threshold":
        return "stress" if vix_level >= threshold else "normal"
    if regime_mode != "hysteresis":
        raise ValueError(f"Unsupported regime mode: {mode}")

    valid_history = _normalized_vix_history(vix_history, fallback=vix_level)
    entry = float(threshold)
    exit_level = float(exit_threshold if exit_threshold is not None else threshold)
    enter_n = max(1, int(stress_persistence))
    exit_n = max(1, int(normal_persistence))

    regime = "normal"
    for idx in range(len(valid_history)):
        prefix = valid_history[: idx + 1]
        if regime == "normal":
            if _tail_all(prefix, threshold=entry, required=enter_n, op="ge"):
                regime = "stress"
        else:
            if _tail_all(prefix, threshold=exit_level, required=exit_n, op="lt"):
                regime = "normal"
    return regime


def _tail_combo_stress(
    vix_history: List[float],
    term_spread_history: List[float],
    *,
    vix_warning_threshold: float,
    term_spread_stress_threshold: float,
    required: int,
) -> bool:
    usable = min(len(vix_history), len(term_spread_history))
    if usable < required:
        return False
    vix_tail = vix_history[-required:]
    spread_tail = term_spread_history[-required:]
    return all(
        float(vix_val) >= float(vix_warning_threshold)
        and float(spread_val) <= float(term_spread_stress_threshold)
        for vix_val, spread_val in zip(vix_tail, spread_tail)
    )


def _safe_finite(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _tail_all(
    values: List[float],
    *,
    threshold: float,
    required: int,
    op: str,
) -> bool:
    if len(values) < required:
        return False
    tail = values[-required:]
    if op == "ge":
        return all(value >= threshold for value in tail)
    if op == "lt":
        return all(value < threshold for value in tail)
    raise ValueError(f"Unsupported tail comparison op: {op}")
