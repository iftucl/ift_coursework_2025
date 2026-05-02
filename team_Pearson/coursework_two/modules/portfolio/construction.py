"""Portfolio target construction for CW2.

This module turns factor scores into final long-only portfolio targets using a
layered process:

1. candidate eligibility from universe screen + risk overlay
2. configurable ranking mode
3. configurable selection mode (fixed N / top % / hybrid)
4. pluggable weighting scheme
5. long-only portfolio constraints (single-name cap, sector cap)
6. optional turnover-aware rebalance around the previous portfolio

The main report configuration still defaults to a transparent equal-weight
portfolio, but the code is structured so that alternative ranking, weighting,
and turnover policies can be enabled without rewriting the pipeline.
"""

from __future__ import annotations

import logging
import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Mapping, Optional

import numpy as np
import pandas as pd

from ..risk.covariance import portfolio_risk_stats

logger = logging.getLogger(__name__)

_WEIGHT_TOL = 1e-12
_CLASS_SUFFIX_RE = re.compile(r"\bclass\s+[a-z0-9-]+\b", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class WeightingOutcome:
    """Resolved raw weighting preferences plus audit metadata."""

    raw_weights: Dict[str, float]
    applied_scheme: str
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class PortfolioConstructionDiagnostics:
    """Per-symbol diagnostic records plus a compact summary for one snapshot."""

    records: List[Dict[str, Any]]
    summary: Dict[str, Any]


class WeightingScheme(ABC):
    """Interface for long-only portfolio weighting schemes."""

    name: str

    @abstractmethod
    def compute_raw_weights(
        self,
        candidates: List[Dict[str, Any]],
        risk_lookup: Mapping[str, Dict[str, Any]],
        *,
        config: Optional[Dict[str, Any]] = None,
        optimization_context: Optional[Dict[str, Any]] = None,
    ) -> WeightingOutcome:
        """Return non-negative raw preference weights keyed by symbol."""


class EqualWeightScheme(WeightingScheme):
    name = "equal"

    def compute_raw_weights(
        self,
        candidates: List[Dict[str, Any]],
        risk_lookup: Mapping[str, Dict[str, Any]],
        *,
        config: Optional[Dict[str, Any]] = None,
        optimization_context: Optional[Dict[str, Any]] = None,
    ) -> WeightingOutcome:
        return WeightingOutcome(
            raw_weights={str(rec["symbol"]): 1.0 for rec in candidates},
            applied_scheme=self.name,
            metadata={},
        )


class EqualTiltScheme(WeightingScheme):
    """Equal-weight base portfolio with a bounded alpha tilt overlay."""

    name = "equal_tilt"

    def compute_raw_weights(
        self,
        candidates: List[Dict[str, Any]],
        risk_lookup: Mapping[str, Dict[str, Any]],
        *,
        config: Optional[Dict[str, Any]] = None,
        optimization_context: Optional[Dict[str, Any]] = None,
    ) -> WeightingOutcome:
        symbols = [str(rec["symbol"]) for rec in candidates]
        if not symbols:
            return WeightingOutcome(raw_weights={}, applied_scheme=self.name, metadata={})

        portfolio_cfg = (config or {}).get("portfolio_construction") or {}
        tilt_cfg = portfolio_cfg.get("alpha_tilt") or {}
        signal_field = str(tilt_cfg.get("signal") or "composite_alpha")
        transform = str(tilt_cfg.get("transform") or "clipped_zscore")
        clip = max(1e-6, float(tilt_cfg.get("clip", 2.0) or 2.0))
        tilt_budget = min(max(float(tilt_cfg.get("budget", 0.12) or 0.12), 0.0), 1.0)
        max_active_per_name = max(0.0, float(tilt_cfg.get("max_active_per_name", 0.015) or 0.015))
        min_weight_epsilon = max(1e-6, float(tilt_cfg.get("min_weight_epsilon", 1e-6) or 1e-6))
        context = optimization_context or {}
        max_single_weight = _safe_float(context.get("max_single_weight"))

        alpha = np.array(
            [_signal_value(rec, signal_field) for rec in candidates],
            dtype=float,
        )
        if not np.all(np.isfinite(alpha)):
            return WeightingOutcome(
                raw_weights={sym: 1.0 for sym in symbols},
                applied_scheme=EqualWeightScheme.name,
                metadata={
                    "tilt_requested": self.name,
                    "fallback_reason": "invalid_alpha_signal",
                },
            )

        transformed = _transform_optimizer_signal(
            alpha,
            method=transform,
            clip=clip,
        )
        centered = transformed - float(np.mean(transformed))
        base_weight = 1.0 / float(len(symbols))
        base_weights = {sym: base_weight for sym in symbols}

        metadata: Dict[str, Any] = {
            "alpha_signal": signal_field,
            "tilt_transform": transform,
            "tilt_clip": clip,
            "tilt_budget": tilt_budget,
            "max_active_per_name": max_active_per_name,
            "base_scheme": EqualWeightScheme.name,
        }
        if (
            tilt_budget <= _WEIGHT_TOL
            or max_active_per_name <= _WEIGHT_TOL
            or np.allclose(centered, 0.0, atol=1e-12)
        ):
            metadata["tilt_applied"] = False
            metadata["tilt_reason"] = "flat_signal_or_zero_budget"
            return WeightingOutcome(
                raw_weights=base_weights,
                applied_scheme=self.name,
                metadata=metadata,
            )

        positive_preferences: Dict[str, float] = {}
        positive_caps: Dict[str, float] = {}
        negative_preferences: Dict[str, float] = {}
        negative_caps: Dict[str, float] = {}
        for idx, sym in enumerate(symbols):
            score = float(centered[idx])
            up_cap = max_active_per_name
            if max_single_weight is not None:
                up_cap = min(up_cap, max(0.0, max_single_weight - base_weight))
            down_cap = min(
                max_active_per_name,
                max(0.0, base_weight - min_weight_epsilon),
            )
            if score > _WEIGHT_TOL and up_cap > _WEIGHT_TOL:
                positive_preferences[sym] = score
                positive_caps[sym] = up_cap
            elif score < -_WEIGHT_TOL and down_cap > _WEIGHT_TOL:
                negative_preferences[sym] = -score
                negative_caps[sym] = down_cap

        if not positive_preferences or not negative_preferences:
            metadata["tilt_applied"] = False
            metadata["tilt_reason"] = "one_sided_signal"
            return WeightingOutcome(
                raw_weights=base_weights,
                applied_scheme=self.name,
                metadata=metadata,
            )

        leg_budget = min(
            0.5 * tilt_budget,
            float(sum(positive_caps.values())),
            float(sum(negative_caps.values())),
        )
        if leg_budget <= _WEIGHT_TOL:
            metadata["tilt_applied"] = False
            metadata["tilt_reason"] = "insufficient_active_capacity"
            return WeightingOutcome(
                raw_weights=base_weights,
                applied_scheme=self.name,
                metadata=metadata,
            )

        positive_alloc = _allocate_mass(
            positive_preferences,
            total_mass=leg_budget,
            caps=positive_caps,
        )
        negative_alloc = _allocate_mass(
            negative_preferences,
            total_mass=leg_budget,
            caps=negative_caps,
        )

        target_weights = {}
        for sym in symbols:
            target_weights[sym] = (
                base_weight
                + float(positive_alloc.get(sym, 0.0))
                - float(negative_alloc.get(sym, 0.0))
            )

        normalized = _normalize_positive_mapping(target_weights, symbols=symbols)
        realized_l1_active = sum(abs(normalized[sym] - base_weight) for sym in symbols)
        metadata["tilt_applied"] = True
        metadata["leg_budget"] = leg_budget
        metadata["realized_l1_active"] = realized_l1_active
        return WeightingOutcome(
            raw_weights=normalized,
            applied_scheme=self.name,
            metadata=metadata,
        )


class ScoreWeightedScheme(WeightingScheme):
    name = "score_weighted"

    def compute_raw_weights(
        self,
        candidates: List[Dict[str, Any]],
        risk_lookup: Mapping[str, Dict[str, Any]],
        *,
        config: Optional[Dict[str, Any]] = None,
        optimization_context: Optional[Dict[str, Any]] = None,
    ) -> WeightingOutcome:
        alpha_by_symbol = {str(rec["symbol"]): float(rec["composite_alpha"]) for rec in candidates}
        min_alpha = min(alpha_by_symbol.values()) if alpha_by_symbol else 0.0
        shift = (-min_alpha + 1e-6) if min_alpha <= 0 else 0.0
        return WeightingOutcome(
            raw_weights={
                symbol: max(alpha + shift, 1e-6) for symbol, alpha in alpha_by_symbol.items()
            },
            applied_scheme=self.name,
            metadata={},
        )


class InverseVolatilityScheme(WeightingScheme):
    name = "inverse_volatility"

    def compute_raw_weights(
        self,
        candidates: List[Dict[str, Any]],
        risk_lookup: Mapping[str, Dict[str, Any]],
        *,
        config: Optional[Dict[str, Any]] = None,
        optimization_context: Optional[Dict[str, Any]] = None,
    ) -> WeightingOutcome:
        vols = [
            _safe_float(risk_lookup.get(str(rec["symbol"]), {}).get("volatility_60d"))
            for rec in candidates
        ]
        valid_vols = [v for v in vols if v is not None and v > 0]
        fallback_vol = _median(valid_vols) if valid_vols else 1.0

        raw: Dict[str, float] = {}
        for rec in candidates:
            sym = str(rec["symbol"])
            vol = _safe_float(risk_lookup.get(sym, {}).get("volatility_60d"))
            use_vol = vol if vol is not None and vol > 0 else fallback_vol
            raw[sym] = 1.0 / max(use_vol, 1e-6)
        return WeightingOutcome(
            raw_weights=raw,
            applied_scheme=self.name,
            metadata={},
        )


class MeanVarianceScheme(WeightingScheme):
    """Long-only alpha-risk optimizer using the configured PIT-clean covariance.

    The formal configuration passes a fundamental-factor covariance matrix.
    Statistical and diagonal covariance estimators remain available as
    fallbacks and ablation baselines.
    """

    name = "mean_variance"

    def __init__(self, fallback_scheme: Optional[WeightingScheme] = None) -> None:
        self._fallback_scheme = fallback_scheme or EqualWeightScheme()

    def compute_raw_weights(
        self,
        candidates: List[Dict[str, Any]],
        risk_lookup: Mapping[str, Dict[str, Any]],
        *,
        config: Optional[Dict[str, Any]] = None,
        optimization_context: Optional[Dict[str, Any]] = None,
    ) -> WeightingOutcome:
        cfg = ((config or {}).get("portfolio_construction") or {}).get("covariance") or {}
        portfolio_cfg = (config or {}).get("portfolio_construction") or {}
        context = optimization_context or {}
        symbols = [str(rec["symbol"]) for rec in candidates]
        if not symbols:
            return WeightingOutcome(raw_weights={}, applied_scheme=self.name, metadata={})

        covariance = _build_candidate_covariance_matrix(
            symbols,
            context.get("covariance_matrix"),
            risk_lookup,
        )
        if covariance.empty:
            return self._fallback(
                "covariance_unavailable",
                candidates,
                risk_lookup,
                config,
                optimization_context,
            )

        signal_field = str(cfg.get("alpha_signal") or "composite_alpha")
        mu = np.array(
            [_signal_value(rec, signal_field) for rec in candidates],
            dtype=float,
        )
        if not np.all(np.isfinite(mu)):
            return self._fallback(
                "invalid_alpha_signal",
                candidates,
                risk_lookup,
                config,
                optimization_context,
            )

        alpha_transform = str(cfg.get("alpha_transform") or "clipped_zscore")
        alpha_clip = max(1e-6, float(cfg.get("alpha_clip", 2.0) or 2.0))
        transformed_mu = _transform_optimizer_signal(
            mu,
            method=alpha_transform,
            clip=alpha_clip,
        )
        if not np.all(np.isfinite(transformed_mu)):
            return self._fallback(
                "invalid_transformed_alpha",
                candidates,
                risk_lookup,
                config,
                optimization_context,
            )

        max_single_weight = _safe_float(context.get("max_single_weight"))
        max_sector_weight = _safe_float(context.get("max_sector_weight"))
        caps = np.array(
            [max_single_weight if max_single_weight is not None else 1.0 for _ in symbols],
            dtype=float,
        )
        if float(caps.sum()) < 1.0 - _WEIGHT_TOL:
            return self._fallback(
                "single_name_cap_infeasible",
                candidates,
                risk_lookup,
                config,
                optimization_context,
            )

        anchor_scheme = str(cfg.get("anchor_scheme") or "equal")
        anchor_weights = _anchor_weight_vector(
            candidates,
            risk_lookup,
            anchor_scheme=anchor_scheme,
            max_single_weight=max_single_weight,
            max_sector_weight=max_sector_weight,
        )
        if anchor_weights is None:
            return self._fallback(
                "anchor_construction_failed",
                candidates,
                risk_lookup,
                config,
                optimization_context,
            )

        max_active_overweight = _safe_float(cfg.get("max_active_overweight"))
        max_active_underweight = _safe_float(cfg.get("max_active_underweight"))
        lower_bounds, upper_bounds = _active_weight_bounds(
            anchor_weights,
            caps,
            max_active_overweight=max_active_overweight,
            max_active_underweight=max_active_underweight,
        )
        if lower_bounds is None or upper_bounds is None:
            return self._fallback(
                "active_bounds_infeasible",
                candidates,
                risk_lookup,
                config,
                optimization_context,
            )

        turnover_penalty = max(0.0, float(cfg.get("turnover_penalty", 0.0) or 0.0))
        reference_weights = _reference_weight_vector(
            symbols,
            context.get("reference_weights"),
        )
        annualize_covariance = bool(cfg.get("annualize_covariance", True))
        covariance_annualization_factor = max(
            1e-6,
            float(cfg.get("covariance_annualization_factor", 252.0) or 252.0),
        )
        optimizer_covariance = covariance.to_numpy(dtype=float)
        if annualize_covariance:
            optimizer_covariance = optimizer_covariance * covariance_annualization_factor
        initial_weights = (
            reference_weights.copy() if reference_weights is not None else anchor_weights.copy()
        )
        optimized = _solve_mean_variance_weights(
            transformed_mu,
            optimizer_covariance,
            caps,
            risk_aversion=max(1e-6, float(cfg.get("risk_aversion", 4.0))),
            ridge_penalty=max(0.0, float(cfg.get("ridge_penalty", 0.05))),
            turnover_penalty=turnover_penalty,
            reference_weights=reference_weights,
            anchor_weights=anchor_weights,
            use_active_risk=bool(cfg.get("use_active_risk", True)),
            max_iter=max(50, int(cfg.get("max_iter", 400))),
            tolerance=max(1e-10, float(cfg.get("tolerance", 1e-8))),
            configured_step_size=_safe_float(cfg.get("step_size")),
            initial_weights=initial_weights,
            lower_bounds=lower_bounds,
            upper_bounds=upper_bounds,
        )
        if optimized is None:
            return self._fallback(
                "optimizer_failed",
                candidates,
                risk_lookup,
                config,
                optimization_context,
            )

        optimized = _stabilize_optimizer_breadth(
            optimized,
            anchor_weights,
            min_active_names=min(len(symbols), int(portfolio_cfg.get("min_names", 1))),
            min_weight_floor=_optimizer_breadth_floor(
                min_target_weight=_safe_float(portfolio_cfg.get("min_target_weight")),
                max_single_weight=max_single_weight,
            ),
        )

        weights = {
            sym: float(weight)
            for sym, weight in zip(symbols, optimized)
            if float(weight) > _WEIGHT_TOL
        }
        metadata = {
            "covariance_method": str(
                context.get("covariance_method")
                or cfg.get("covariance_method")
                or "diagonal_shrinkage"
            ),
            "covariance_lookback_days": int(
                context.get("covariance_lookback_days") or cfg.get("lookback_days", 252)
            ),
            "risk_aversion": float(cfg.get("risk_aversion", 4.0)),
            "ridge_penalty": float(cfg.get("ridge_penalty", 0.05)),
            "turnover_penalty": turnover_penalty,
            "alpha_signal": signal_field,
            "alpha_transform": alpha_transform,
            "alpha_clip": alpha_clip,
            "anchor_scheme": anchor_scheme,
            "use_active_risk": bool(cfg.get("use_active_risk", True)),
            "annualize_covariance": annualize_covariance,
            "covariance_annualization_factor": covariance_annualization_factor,
            "reference_weights_available": reference_weights is not None,
            "max_active_overweight": max_active_overweight,
            "max_active_underweight": max_active_underweight,
        }
        risk_stats = portfolio_risk_stats(weights, covariance, context.get("sector_map") or {})
        if risk_stats:
            metadata["ex_ante_volatility_ann"] = risk_stats.get("annualized_volatility")
            metadata["diversification_ratio"] = risk_stats.get("diversification_ratio")
            metadata["effective_risk_bets"] = risk_stats.get("effective_risk_bets")
        return WeightingOutcome(
            raw_weights=weights,
            applied_scheme=self.name,
            metadata=metadata,
        )

    def _fallback(
        self,
        reason: str,
        candidates: List[Dict[str, Any]],
        risk_lookup: Mapping[str, Dict[str, Any]],
        config: Optional[Dict[str, Any]],
        optimization_context: Optional[Dict[str, Any]],
    ) -> WeightingOutcome:
        fallback = self._fallback_scheme.compute_raw_weights(
            candidates,
            risk_lookup,
            config=config,
            optimization_context=optimization_context,
        )
        metadata = dict(fallback.metadata)
        metadata["optimizer_requested"] = self.name
        metadata["fallback_reason"] = reason
        return WeightingOutcome(
            raw_weights=fallback.raw_weights,
            applied_scheme=fallback.applied_scheme,
            metadata=metadata,
        )


_WEIGHTING_SCHEME_REGISTRY: Dict[str, WeightingScheme] = {
    scheme.name: scheme
    for scheme in (
        EqualWeightScheme(),
        EqualTiltScheme(),
        ScoreWeightedScheme(),
        InverseVolatilityScheme(),
        MeanVarianceScheme(),
    )
}


def build_portfolio_targets(
    factor_scores: List[Dict[str, Any]],
    risk_overlay_records: List[Dict[str, Any]],
    universe_screen_records: List[Dict[str, Any]],
    company_info_map: Optional[Dict[str, Dict[str, Any]]] = None,
    *,
    covariance_matrix: Optional[Any] = None,
    covariance_meta: Optional[Dict[str, Any]] = None,
    previous_positions: Optional[List[Dict[str, Any]]] = None,
    config: Optional[Dict[str, Any]] = None,
    return_diagnostics: bool = False,
) -> Any:
    """Select eligible alpha candidates and assign constrained long-only target weights."""
    cfg = (config or {}).get("portfolio_construction", {})
    portfolio_name = str(cfg.get("portfolio_name") or "cw2_core_equity")
    ranking_mode = str(cfg.get("ranking_mode") or "global").strip().lower()
    ranking_blend_global_weight = _safe_float(cfg.get("ranking_blend_global_weight", 0.70))
    selection_mode = str(cfg.get("selection_mode") or "fixed_n").strip().lower()
    min_names = max(1, int(cfg.get("min_names", 15)))
    min_candidate_pool = max(1, int(cfg.get("min_candidate_pool", 10)))
    min_target_weight = max(0.0, float(cfg.get("min_target_weight", 0.0) or 0.0))
    weighting_name = str(cfg.get("weighting") or "equal").strip().lower()
    max_single_weight = _safe_float(cfg.get("max_single_weight", 0.10))
    max_sector_weight = _safe_float(cfg.get("max_sector_weight", 0.25))
    relax_sector_cap = bool(cfg.get("relax_sector_cap_if_needed", True))
    turnover_cap = _safe_float(cfg.get("turnover_cap"))
    deduplicate_issuer_positions = bool(cfg.get("deduplicate_issuer_positions", True))

    weighting_scheme = _resolve_weighting_scheme(weighting_name)

    universe_lookup = {
        str(rec["symbol"]): rec for rec in universe_screen_records if rec.get("symbol")
    }
    risk_lookup = {str(rec["symbol"]): rec for rec in risk_overlay_records}
    info_map = company_info_map or {}
    factor_scores = _apply_alpha_smoothing(
        factor_scores,
        config=config,
    )

    candidates: List[Dict[str, Any]] = []
    for rec in factor_scores:
        sym = str(rec.get("symbol") or "").strip()
        alpha = rec.get("composite_alpha")
        if not sym or alpha is None:
            continue
        try:
            alpha_val = float(alpha)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(alpha_val):
            continue
        universe_rec = universe_lookup.get(sym, {})
        if not bool(universe_rec.get("pass_all")):
            continue
        if not bool(risk_lookup.get(sym, {}).get("pass_all")):
            continue
        info = info_map.get(sym, {})
        candidates.append(
            {
                **rec,
                "symbol": sym,
                "composite_alpha": alpha_val,
                "gics_sector": str(info.get("gics_sector") or "Unknown"),
                "country": info.get("country"),
                "security": info.get("security"),
                "liquidity_20d": _safe_float(universe_rec.get("liquidity_20d")),
            }
        )

    if not candidates:
        logger.info("portfolio_targets: no eligible candidates after universe and risk filters")
        return _package_portfolio_result(
            [],
            return_diagnostics=return_diagnostics,
            diagnostic_records=[],
            diagnostic_summary={
                "status": "no_eligible_candidates",
                "candidate_count": 0,
                "selected_signal_count": 0,
                "final_name_count": 0,
                "requested_weighting": weighting_name,
                "applied_weighting": weighting_name,
            },
        )

    previous_lookup = _normalize_previous_positions(previous_positions)
    if deduplicate_issuer_positions:
        candidates, issuer_dedup_removed = _deduplicate_candidates_by_issuer(
            candidates,
            previous_lookup=previous_lookup,
        )
        if issuer_dedup_removed > 0:
            logger.info(
                "portfolio_targets: removed %d duplicate share-class candidates by issuer portfolio=%s",
                issuer_dedup_removed,
                portfolio_name,
            )

    candidates = _annotate_ranking_scores(
        candidates,
        ranking_mode=ranking_mode,
        blend_global_weight=ranking_blend_global_weight,
    )
    candidates = sorted(candidates, key=_candidate_sort_key)
    candidate_map = {str(rec["symbol"]): rec for rec in candidates}

    if len(candidates) < min_candidate_pool:
        logger.warning(
            "portfolio_targets: candidate pool below minimum guard portfolio=%s candidates=%d min_candidate_pool=%d",
            portfolio_name,
            len(candidates),
            min_candidate_pool,
        )
        return _package_portfolio_result(
            [],
            return_diagnostics=return_diagnostics,
            diagnostic_records=[],
            diagnostic_summary={
                "status": "candidate_pool_below_minimum",
                "candidate_count": len(candidates),
                "selected_signal_count": 0,
                "final_name_count": 0,
                "requested_weighting": weighting_name,
                "applied_weighting": weighting_name,
                "min_candidate_pool": min_candidate_pool,
            },
        )

    target_count = _resolve_target_count(
        candidate_count=len(candidates),
        selection_mode=selection_mode,
        cfg=cfg,
        min_names=min_names,
    )
    top_ranked_symbols = {str(rec["symbol"]) for rec in candidates[:target_count]}
    selected = _select_candidates_with_sector_diversification(
        candidates,
        target_count=target_count,
        max_sector_weight=max_sector_weight,
        relax_sector_cap=relax_sector_cap,
    )
    if relax_sector_cap:
        selected = _repair_selection_for_capacity(
            candidates,
            selected,
            target_count=target_count,
            max_single_weight=max_single_weight,
            max_sector_weight=max_sector_weight,
        )
    selected = _apply_incumbent_exit_buffer(
        candidates,
        selected,
        previous_lookup,
        incumbent_exit_rank=_safe_float(cfg.get("incumbent_exit_rank")),
    )
    selected, new_name_cap_meta = _apply_new_name_cap(
        candidates,
        selected,
        previous_lookup,
        max_new_names_per_rebalance=int(cfg.get("max_new_names_per_rebalance", 0) or 0),
    )
    if len(selected) < min(target_count, min_names):
        logger.warning(
            "portfolio_targets: selected names below minimum portfolio=%s selected=%d target=%d min_names=%d",
            portfolio_name,
            len(selected),
            target_count,
            min_names,
        )
        diagnostics = _build_portfolio_construction_diagnostics(
            portfolio_name=portfolio_name,
            candidates=candidates,
            selected=selected,
            top_ranked_symbols=top_ranked_symbols,
            ranking_mode=ranking_mode,
            weighting_requested=weighting_name,
            weighting_outcome=WeightingOutcome(
                raw_weights={}, applied_scheme=weighting_name, metadata={}
            ),
            constrained_weights={},
            final_weights={},
            previous_lookup={},
            turnover_meta={
                "turnover_cap": turnover_cap,
                "realized_turnover": None,
                "turnover_limited": False,
                **new_name_cap_meta,
            },
            max_single_weight=max_single_weight,
            max_sector_weight=max_sector_weight,
            covariance_meta=covariance_meta,
            status="selected_names_below_minimum",
        )
        return _package_portfolio_result(
            [],
            return_diagnostics=return_diagnostics,
            diagnostic_records=diagnostics.records,
            diagnostic_summary=diagnostics.summary,
        )

    selected_map = {str(rec["symbol"]): rec for rec in selected}
    optimizer_reference_weights = _project_previous_weights_to_feasible_baseline(
        selected_map,
        previous_lookup,
        max_single_weight=max_single_weight,
        max_sector_weight=max_sector_weight,
    )
    weighting_outcome = weighting_scheme.compute_raw_weights(
        selected,
        risk_lookup,
        config=config,
        optimization_context={
            "covariance_matrix": covariance_matrix,
            "covariance_method": (covariance_meta or {}).get("covariance_method"),
            "covariance_lookback_days": (covariance_meta or {}).get("lookback_days"),
            "max_single_weight": max_single_weight,
            "max_sector_weight": max_sector_weight,
            "sector_map": {
                str(rec["symbol"]): str(rec.get("gics_sector") or "Unknown") for rec in selected
            },
            "reference_weights": optimizer_reference_weights,
        },
    )
    applied_weighting_name = str(weighting_outcome.applied_scheme or weighting_name)
    applied_max_sector_weight = max_sector_weight
    try:
        target_weights = _apply_weight_constraints(
            selected,
            weighting_outcome.raw_weights,
            max_single_weight=max_single_weight,
            max_sector_weight=applied_max_sector_weight,
        )
    except ValueError as exc:
        relaxed_sector_weight = (
            _minimum_feasible_sector_cap(selected, max_single_weight)
            if relax_sector_cap and max_sector_weight is not None
            else None
        )
        if relaxed_sector_weight is not None and relaxed_sector_weight > max_sector_weight + 1e-8:
            logger.warning(
                "portfolio_targets: relaxing sector cap for feasibility portfolio=%s selection_mode=%s weighting=%s old_cap=%.4f new_cap=%.4f selected=%d",
                portfolio_name,
                selection_mode,
                weighting_name,
                max_sector_weight,
                relaxed_sector_weight,
                len(selected),
            )
            applied_max_sector_weight = relaxed_sector_weight
            try:
                target_weights = _apply_weight_constraints(
                    selected,
                    weighting_outcome.raw_weights,
                    max_single_weight=max_single_weight,
                    max_sector_weight=applied_max_sector_weight,
                )
            except ValueError as relaxed_exc:
                logger.warning(
                    "portfolio_targets: constraint application still failed after relaxing sector cap portfolio=%s selection_mode=%s weighting=%s relaxed_cap=%.4f error=%s",
                    portfolio_name,
                    selection_mode,
                    weighting_name,
                    applied_max_sector_weight,
                    relaxed_exc,
                )
                diagnostics = _build_portfolio_construction_diagnostics(
                    portfolio_name=portfolio_name,
                    candidates=candidates,
                    selected=selected,
                    top_ranked_symbols=top_ranked_symbols,
                    ranking_mode=ranking_mode,
                    weighting_requested=weighting_name,
                    weighting_outcome=weighting_outcome,
                    constrained_weights={},
                    final_weights={},
                    previous_lookup=_normalize_previous_positions(previous_positions),
                    turnover_meta={
                        "turnover_cap": turnover_cap,
                        "realized_turnover": None,
                        "turnover_limited": False,
                        **new_name_cap_meta,
                    },
                    max_single_weight=max_single_weight,
                    max_sector_weight=applied_max_sector_weight,
                    covariance_meta=covariance_meta,
                    status="constraint_application_failed",
                )
                return _package_portfolio_result(
                    [],
                    return_diagnostics=return_diagnostics,
                    diagnostic_records=diagnostics.records,
                    diagnostic_summary=diagnostics.summary,
                )
        else:
            logger.warning(
                "portfolio_targets: constraint application failed portfolio=%s selection_mode=%s weighting=%s error=%s",
                portfolio_name,
                selection_mode,
                weighting_name,
                exc,
            )
            diagnostics = _build_portfolio_construction_diagnostics(
                portfolio_name=portfolio_name,
                candidates=candidates,
                selected=selected,
                top_ranked_symbols=top_ranked_symbols,
                ranking_mode=ranking_mode,
                weighting_requested=weighting_name,
                weighting_outcome=weighting_outcome,
                constrained_weights={},
                final_weights={},
                previous_lookup=_normalize_previous_positions(previous_positions),
                turnover_meta={
                    "turnover_cap": turnover_cap,
                    "realized_turnover": None,
                    "turnover_limited": False,
                    **new_name_cap_meta,
                },
                max_single_weight=max_single_weight,
                max_sector_weight=max_sector_weight,
                covariance_meta=covariance_meta,
                status="constraint_application_failed",
            )
            return _package_portfolio_result(
                [],
                return_diagnostics=return_diagnostics,
                diagnostic_records=diagnostics.records,
                diagnostic_summary=diagnostics.summary,
            )

    final_weights, no_trade_meta = _apply_no_trade_band(
        target_weights,
        candidate_map,
        previous_lookup,
        no_trade_band_weight=_safe_float(cfg.get("no_trade_band_weight")),
        max_single_weight=max_single_weight,
        max_sector_weight=applied_max_sector_weight,
    )
    final_weights, trade_cap_meta = _apply_per_name_trade_cap(
        final_weights,
        candidate_map,
        previous_lookup,
        per_name_max_trade_weight=_safe_float(cfg.get("per_name_max_trade_weight")),
        max_single_weight=max_single_weight,
        max_sector_weight=applied_max_sector_weight,
    )
    final_weights, turnover_meta = _apply_turnover_overlay(
        final_weights,
        candidate_map,
        previous_lookup,
        turnover_cap=turnover_cap,
        max_single_weight=max_single_weight,
        max_sector_weight=applied_max_sector_weight,
    )
    turnover_meta = {
        **turnover_meta,
        **new_name_cap_meta,
        **no_trade_meta,
        **trade_cap_meta,
    }
    final_weights, turnover_meta = _apply_min_target_weight_floor(
        final_weights,
        candidate_map,
        previous_weights=previous_lookup,
        min_target_weight=min_target_weight,
        min_names=min_names,
        max_single_weight=max_single_weight,
        max_sector_weight=applied_max_sector_weight,
        turnover_meta=turnover_meta,
    )

    selected_symbols = {str(rec["symbol"]) for rec in selected}
    ordered_symbols = [
        sym
        for sym in sorted(final_weights, key=lambda sym: _candidate_sort_key(candidate_map[sym]))
        if final_weights[sym] > _WEIGHT_TOL
    ]

    out: List[Dict[str, Any]] = []
    for idx, sym in enumerate(ordered_symbols, start=1):
        rec = candidate_map[sym]
        previous_weight = previous_lookup.get(sym, 0.0) if previous_lookup else 0.0
        target_weight = final_weights[sym]
        out.append(
            {
                "as_of_date": rec["as_of_date"],
                "portfolio_name": portfolio_name,
                "symbol": sym,
                "selection_rank": idx,
                "selected_signal": sym in selected_symbols,
                "target_weight": target_weight,
                "weighting_scheme": applied_weighting_name,
                "ranking_mode": ranking_mode,
                "ranking_score": rec.get("ranking_score"),
                "composite_alpha": rec["composite_alpha"],
                "regime": rec.get("regime"),
                "gics_sector": rec.get("gics_sector"),
                "country": rec.get("country"),
                "previous_weight": round(previous_weight, 8),
                "trade_weight": round(target_weight - previous_weight, 8),
                "turnover_cap": turnover_meta.get("turnover_cap"),
                "realized_turnover": turnover_meta.get("realized_turnover"),
                "turnover_limited": turnover_meta.get("turnover_limited", False),
            }
        )

    logger.info(
        "portfolio_targets: portfolio=%s candidates=%d selected=%d final_names=%d ranking_mode=%s selection_mode=%s requested_weighting=%s applied_weighting=%s cov_method=%s ex_ante_vol=%.4f turnover_cap=%s turnover=%.4f limited=%s max_new_names=%s deferred_new_names=%d no_trade_band=%s frozen_names=%d per_name_trade_cap=%s clipped_names=%d max_single=%s max_sector=%s",
        portfolio_name,
        len(candidates),
        len(selected),
        len(out),
        ranking_mode,
        selection_mode,
        weighting_name,
        applied_weighting_name,
        weighting_outcome.metadata.get("covariance_method") or "n/a",
        float(weighting_outcome.metadata.get("ex_ante_volatility_ann") or 0.0),
        f"{turnover_cap:.2f}" if turnover_cap is not None else "disabled",
        turnover_meta.get("realized_turnover") or 0.0,
        turnover_meta.get("turnover_limited", False),
        (
            int(new_name_cap_meta.get("max_new_names_per_rebalance") or 0)
            if int(new_name_cap_meta.get("max_new_names_per_rebalance") or 0) > 0
            else "disabled"
        ),
        int(new_name_cap_meta.get("deferred_new_names_count") or 0),
        (
            f"{float(no_trade_meta.get('no_trade_band_weight') or 0.0):.4f}"
            if float(no_trade_meta.get("no_trade_band_weight") or 0.0) > _WEIGHT_TOL
            else "disabled"
        ),
        int(no_trade_meta.get("no_trade_band_frozen_names") or 0),
        (
            f"{float(trade_cap_meta.get('per_name_max_trade_weight') or 0.0):.4f}"
            if float(trade_cap_meta.get("per_name_max_trade_weight") or 0.0) > _WEIGHT_TOL
            else "disabled"
        ),
        int(trade_cap_meta.get("per_name_max_trade_clipped_names") or 0),
        f"{max_single_weight:.2f}" if max_single_weight is not None else "disabled",
        (
            f"{applied_max_sector_weight:.2f}"
            if applied_max_sector_weight is not None
            else "disabled"
        ),
    )
    diagnostics = _build_portfolio_construction_diagnostics(
        portfolio_name=portfolio_name,
        candidates=candidates,
        selected=selected,
        top_ranked_symbols=top_ranked_symbols,
        ranking_mode=ranking_mode,
        weighting_requested=weighting_name,
        weighting_outcome=weighting_outcome,
        constrained_weights=target_weights,
        final_weights=final_weights,
        previous_lookup=previous_lookup,
        turnover_meta=turnover_meta,
        max_single_weight=max_single_weight,
        max_sector_weight=applied_max_sector_weight,
        covariance_meta=covariance_meta,
        status="completed",
    )
    return _package_portfolio_result(
        out,
        return_diagnostics=return_diagnostics,
        diagnostic_records=diagnostics.records,
        diagnostic_summary=diagnostics.summary,
    )


def _apply_alpha_smoothing(
    factor_scores: List[Dict[str, Any]],
    *,
    config: Optional[Dict[str, Any]],
    history_loader: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    records = [dict(record) for record in factor_scores]
    cfg = (((config or {}).get("portfolio_construction") or {}).get("alpha_smoothing")) or {}
    if not bool(cfg.get("enabled")) or not records:
        return records

    method = str(cfg.get("method") or "ewma").strip().lower()
    if method != "ewma":
        raise ValueError(f"Unsupported alpha_smoothing.method: {method}")

    as_of_date = _coerce_portfolio_as_of_date(records)
    if as_of_date is None:
        return records

    symbols = sorted(
        {
            str(record.get("symbol") or "").strip()
            for record in records
            if str(record.get("symbol") or "").strip()
        }
    )
    if not symbols:
        return records

    half_life_days = max(1e-6, float(cfg.get("half_life_days") or 60.0))
    max_lookback_days = max(1, int(cfg.get("max_lookback_days") or 252))
    min_history_points = max(0, int(cfg.get("min_history_points") or 0))
    loader = history_loader or _load_historical_composite_alpha
    history_by_symbol = loader(
        as_of_date=as_of_date,
        symbols=symbols,
        max_lookback_days=max_lookback_days,
    )

    smoothed_count = 0
    for record in records:
        raw_alpha = _safe_float(record.get("composite_alpha"))
        record["raw_composite_alpha"] = raw_alpha
        if raw_alpha is None:
            continue

        symbol = str(record.get("symbol") or "").strip()
        history = history_by_symbol.get(symbol) or []
        if len(history) < min_history_points:
            continue

        weighted_sum = raw_alpha
        weight_sum = 1.0
        for obs_date, obs_alpha in history:
            age_days = max(0, (as_of_date - obs_date).days)
            decay_weight = 0.5 ** (float(age_days) / half_life_days)
            weighted_sum += decay_weight * obs_alpha
            weight_sum += decay_weight

        if weight_sum <= _WEIGHT_TOL:
            continue
        record["composite_alpha"] = weighted_sum / weight_sum
        record["alpha_smoothing_method"] = method
        record["alpha_smoothing_history_points"] = len(history)
        smoothed_count += 1

    logger.info(
        "portfolio_targets: alpha smoothing method=%s half_life_days=%.1f lookback_days=%d min_history_points=%d smoothed_symbols=%d/%d",
        method,
        half_life_days,
        max_lookback_days,
        min_history_points,
        smoothed_count,
        len(records),
    )
    return records


def _package_portfolio_result(
    target_records: List[Dict[str, Any]],
    *,
    return_diagnostics: bool,
    diagnostic_records: List[Dict[str, Any]],
    diagnostic_summary: Dict[str, Any],
) -> Any:
    if not return_diagnostics:
        return target_records
    return target_records, PortfolioConstructionDiagnostics(
        records=diagnostic_records,
        summary=diagnostic_summary,
    )


def _build_portfolio_construction_diagnostics(
    *,
    portfolio_name: str,
    candidates: List[Dict[str, Any]],
    selected: List[Dict[str, Any]],
    top_ranked_symbols: set[str],
    ranking_mode: str,
    weighting_requested: str,
    weighting_outcome: WeightingOutcome,
    constrained_weights: Mapping[str, float],
    final_weights: Mapping[str, float],
    previous_lookup: Mapping[str, float],
    turnover_meta: Mapping[str, Any],
    max_single_weight: Optional[float],
    max_sector_weight: Optional[float],
    covariance_meta: Optional[Dict[str, Any]],
    status: str,
) -> PortfolioConstructionDiagnostics:
    selected_symbols = {str(rec["symbol"]) for rec in selected}
    sectors = {str(rec["symbol"]): str(rec.get("gics_sector") or "Unknown") for rec in candidates}
    raw_preferences = {
        sym: float(weighting_outcome.raw_weights.get(sym, 0.0)) for sym in selected_symbols
    }
    pre_constraint_weights = (
        _normalize_positive_mapping(raw_preferences, symbols=sorted(selected_symbols))
        if selected_symbols and any(value > _WEIGHT_TOL for value in raw_preferences.values())
        else {}
    )
    normalized_constrained = {
        str(sym): float(weight)
        for sym, weight in constrained_weights.items()
        if float(weight) > _WEIGHT_TOL
    }
    normalized_final = {
        str(sym): float(weight)
        for sym, weight in final_weights.items()
        if float(weight) > _WEIGHT_TOL
    }
    sector_pre = (
        _sector_weight_sums(pre_constraint_weights, sectors) if pre_constraint_weights else {}
    )
    sector_post = (
        _sector_weight_sums(normalized_constrained, sectors) if normalized_constrained else {}
    )
    sector_final = _sector_weight_sums(normalized_final, sectors) if normalized_final else {}
    candidate_rank = {str(rec["symbol"]): idx for idx, rec in enumerate(candidates, start=1)}
    drop_reason_counts: Dict[str, int] = {}
    binding_counts = {
        "single_name_cap": 0,
        "sector_cap": 0,
        "turnover_overlay": 0,
    }
    records: List[Dict[str, Any]] = []

    for rec in candidates:
        sym = str(rec["symbol"])
        sector = sectors.get(sym, "Unknown")
        pre_constraint = _safe_float(pre_constraint_weights.get(sym))
        constrained = _safe_float(normalized_constrained.get(sym, 0.0))
        final_weight = _safe_float(normalized_final.get(sym, 0.0))
        previous_weight = _safe_float(previous_lookup.get(sym, 0.0))
        selection_drop_reason = None
        if sym not in selected_symbols:
            selection_drop_reason = (
                "sector_diversification" if sym in top_ranked_symbols else "ranking_cutoff"
            )
            drop_reason_counts[selection_drop_reason] = (
                drop_reason_counts.get(selection_drop_reason, 0) + 1
            )

        single_name_cap_binding = bool(
            max_single_weight is not None
            and pre_constraint is not None
            and pre_constraint > max_single_weight + _WEIGHT_TOL
            and (constrained or 0.0) < pre_constraint - _WEIGHT_TOL
        )
        sector_cap_binding = bool(
            max_sector_weight is not None
            and pre_constraint is not None
            and sector_pre.get(sector, 0.0) > max_sector_weight + _WEIGHT_TOL
            and (constrained or 0.0) < pre_constraint - _WEIGHT_TOL
        )
        turnover_binding = bool(
            turnover_meta.get("turnover_limited", False)
            and abs((final_weight or 0.0) - (constrained or 0.0)) > _WEIGHT_TOL
        )
        if single_name_cap_binding:
            binding_counts["single_name_cap"] += 1
        if sector_cap_binding:
            binding_counts["sector_cap"] += 1
        if turnover_binding:
            binding_counts["turnover_overlay"] += 1

        binding_reasons = []
        if single_name_cap_binding:
            binding_reasons.append("single_name_cap")
        if sector_cap_binding:
            binding_reasons.append("sector_cap")
        if turnover_binding:
            binding_reasons.append("turnover_overlay")

        records.append(
            {
                "as_of_date": rec.get("as_of_date"),
                "portfolio_name": portfolio_name,
                "symbol": sym,
                "candidate_rank": candidate_rank.get(sym),
                "selected_signal": sym in selected_symbols,
                "selection_drop_reason": selection_drop_reason,
                "gics_sector": sector,
                "country": rec.get("country"),
                "ranking_mode": ranking_mode,
                "ranking_score": _round_optional(rec.get("ranking_score")),
                "composite_alpha": _round_optional(rec.get("composite_alpha")),
                "optimizer_requested": weighting_requested,
                "optimizer_applied": str(weighting_outcome.applied_scheme or weighting_requested),
                "raw_preference_weight": _round_optional(raw_preferences.get(sym)),
                "pre_constraint_weight": _round_optional(pre_constraint),
                "constrained_weight": _round_optional(constrained),
                "final_target_weight": _round_optional(final_weight or 0.0),
                "previous_weight": _round_optional(previous_weight or 0.0),
                "constraint_weight_delta": _round_optional(
                    None if pre_constraint is None else (constrained or 0.0) - pre_constraint
                ),
                "turnover_weight_delta": _round_optional(
                    None if pre_constraint is None else (final_weight or 0.0) - (constrained or 0.0)
                ),
                "total_weight_delta": _round_optional(
                    None if pre_constraint is None else (final_weight or 0.0) - pre_constraint
                ),
                "sector_weight_pre_constraint": _round_optional(sector_pre.get(sector)),
                "sector_weight_post_constraint": _round_optional(sector_post.get(sector)),
                "sector_weight_final": _round_optional(sector_final.get(sector)),
                "max_single_weight": _round_optional(max_single_weight),
                "max_sector_weight": _round_optional(max_sector_weight),
                "single_name_cap_binding": single_name_cap_binding,
                "sector_cap_binding": sector_cap_binding,
                "turnover_limited": bool(turnover_meta.get("turnover_limited", False)),
                "turnover_cap": _round_optional(turnover_meta.get("turnover_cap")),
                "realized_turnover": _round_optional(turnover_meta.get("realized_turnover")),
                "covariance_method": str(
                    weighting_outcome.metadata.get("covariance_method")
                    or (covariance_meta or {}).get("covariance_method")
                    or (covariance_meta or {}).get("method")
                    or ""
                )
                or None,
                "optimizer_fallback_reason": weighting_outcome.metadata.get("fallback_reason"),
                "diagnostic_json": {
                    "binding_reasons": binding_reasons,
                    "global_rank_score": _round_optional(rec.get("global_rank_score")),
                    "sector_rank_score": _round_optional(rec.get("sector_rank_score")),
                    "optimizer_metadata": dict(weighting_outcome.metadata),
                },
            }
        )

    summary = {
        "status": status,
        "candidate_count": len(candidates),
        "selected_signal_count": len(selected_symbols),
        "final_name_count": sum(1 for value in normalized_final.values() if value > _WEIGHT_TOL),
        "requested_weighting": weighting_requested,
        "applied_weighting": str(weighting_outcome.applied_scheme or weighting_requested),
        "constraint_binding_counts": binding_counts,
        "drop_reason_counts": drop_reason_counts,
        "turnover_limited": bool(turnover_meta.get("turnover_limited", False)),
        "turnover_cap": _round_optional(turnover_meta.get("turnover_cap")),
        "realized_turnover": _round_optional(turnover_meta.get("realized_turnover")),
        "covariance_method": (
            weighting_outcome.metadata.get("covariance_method")
            or (covariance_meta or {}).get("covariance_method")
            or (covariance_meta or {}).get("method")
        ),
    }
    return PortfolioConstructionDiagnostics(records=records, summary=summary)


def _round_optional(value: Any, digits: int = 8) -> Optional[float]:
    parsed = _safe_float(value)
    if parsed is None:
        return None
    return round(parsed, digits)


def _rounded_weight_mapping(
    weights: Mapping[str, float],
    *,
    digits: int = 8,
) -> Dict[str, float]:
    rounded = {
        str(sym): round(float(weight), digits)
        for sym, weight in weights.items()
        if float(weight) > _WEIGHT_TOL
    }
    if not rounded:
        return {}

    residual = round(1.0 - sum(rounded.values()), digits)
    if abs(residual) <= 10 ** (-digits):
        key = max(rounded, key=rounded.get)
        rounded[key] = round(rounded[key] + residual, digits)

    return {sym: weight for sym, weight in rounded.items() if weight > _WEIGHT_TOL}


def _resolve_weighting_scheme(name: str) -> WeightingScheme:
    scheme = _WEIGHTING_SCHEME_REGISTRY.get(name)
    if scheme is None:
        supported = ", ".join(sorted(_WEIGHTING_SCHEME_REGISTRY))
        raise ValueError(f"Unsupported weighting scheme: {name}. Supported: {supported}")
    return scheme


def _resolve_target_count(
    *,
    candidate_count: int,
    selection_mode: str,
    cfg: Dict[str, Any],
    min_names: int,
) -> int:
    top_n = max(1, int(cfg.get("top_n", 25)))
    top_pct = _safe_float(cfg.get("top_pct", 0.20))
    hybrid_min_n = max(1, int(cfg.get("hybrid_min_n", min_names)))
    hybrid_max_n = max(hybrid_min_n, int(cfg.get("hybrid_max_n", top_n)))

    if selection_mode == "fixed_n":
        target = top_n
    elif selection_mode == "top_pct":
        if top_pct is None or not (0.0 < top_pct <= 1.0):
            raise ValueError(f"Invalid top_pct for selection_mode=top_pct: {top_pct}")
        target = int(math.ceil(candidate_count * top_pct))
    elif selection_mode == "hybrid":
        if top_pct is None or not (0.0 < top_pct <= 1.0):
            raise ValueError(f"Invalid top_pct for selection_mode=hybrid: {top_pct}")
        target = int(math.ceil(candidate_count * top_pct))
        target = min(max(target, hybrid_min_n), hybrid_max_n)
    else:
        raise ValueError(f"Unsupported selection_mode: {selection_mode}")

    if candidate_count >= min_names:
        target = max(target, min_names)
    target = max(1, min(candidate_count, target))
    return target


def _annotate_ranking_scores(
    candidates: List[Dict[str, Any]],
    *,
    ranking_mode: str,
    blend_global_weight: Optional[float],
) -> List[Dict[str, Any]]:
    mode = str(ranking_mode or "global").strip().lower()
    if mode not in {"global", "sector_relative", "blended"}:
        raise ValueError(f"Unsupported ranking_mode: {ranking_mode}")

    global_scores = _global_rank_score_map(candidates)
    sector_scores = _sector_rank_score_map(candidates)
    blend = 0.70 if blend_global_weight is None else min(max(blend_global_weight, 0.0), 1.0)

    annotated: List[Dict[str, Any]] = []
    for rec in candidates:
        sym = str(rec["symbol"])
        global_score = global_scores.get(sym, 0.0)
        sector_score = sector_scores.get(sym, global_score)
        if mode == "global":
            ranking_score = global_score
        elif mode == "sector_relative":
            ranking_score = sector_score
        else:
            ranking_score = blend * global_score + (1.0 - blend) * sector_score

        annotated.append(
            {
                **rec,
                "global_rank_score": global_score,
                "sector_rank_score": sector_score,
                "ranking_score": ranking_score,
            }
        )
    return annotated


def _global_rank_score_map(candidates: List[Dict[str, Any]]) -> Dict[str, float]:
    ordered = sorted(
        candidates,
        key=lambda rec: (-float(rec["composite_alpha"]), str(rec["symbol"])),
    )
    return _rank_score_map_from_sorted_records(ordered)


def _sector_rank_score_map(candidates: List[Dict[str, Any]]) -> Dict[str, float]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for rec in candidates:
        sector = str(rec.get("gics_sector") or "Unknown")
        grouped.setdefault(sector, []).append(rec)

    out: Dict[str, float] = {}
    for records in grouped.values():
        ordered = sorted(
            records,
            key=lambda rec: (-float(rec["composite_alpha"]), str(rec["symbol"])),
        )
        out.update(_rank_score_map_from_sorted_records(ordered))
    return out


def _rank_score_map_from_sorted_records(
    records: List[Dict[str, Any]],
) -> Dict[str, float]:
    count = len(records)
    if count <= 1:
        return {str(rec["symbol"]): 1.0 for rec in records}

    scores: Dict[str, float] = {}
    denom = count - 1
    for idx, rec in enumerate(records):
        scores[str(rec["symbol"])] = 1.0 - (idx / denom)
    return scores


def _candidate_sort_key(rec: Mapping[str, Any]) -> tuple[float, float, str]:
    ranking_score = _safe_float(rec.get("ranking_score"))
    alpha = _safe_float(rec.get("composite_alpha"))
    return (
        -(ranking_score if ranking_score is not None else -math.inf),
        -(alpha if alpha is not None else -math.inf),
        str(rec.get("symbol") or ""),
    )


def _deduplicate_candidates_by_issuer(
    candidates: List[Dict[str, Any]],
    *,
    previous_lookup: Mapping[str, float],
) -> tuple[List[Dict[str, Any]], int]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for rec in candidates:
        issuer_key = _issuer_key_for_candidate(rec)
        grouped.setdefault(issuer_key, []).append(rec)

    deduped: List[Dict[str, Any]] = []
    removed = 0
    for issuer_key, issuer_candidates in grouped.items():
        if len(issuer_candidates) == 1:
            deduped.append(issuer_candidates[0])
            continue
        selected = min(
            issuer_candidates,
            key=lambda rec: _issuer_candidate_priority(
                rec,
                previous_lookup=previous_lookup,
            ),
        )
        deduped.append(selected)
        removed += len(issuer_candidates) - 1
        logger.info(
            "portfolio_targets: issuer_dedup issuer=%s kept=%s dropped=%s",
            issuer_key,
            selected.get("symbol"),
            sorted(
                str(rec.get("symbol") or "")
                for rec in issuer_candidates
                if str(rec.get("symbol") or "") != str(selected.get("symbol") or "")
            ),
        )
    return deduped, removed


def _issuer_candidate_priority(
    rec: Mapping[str, Any],
    *,
    previous_lookup: Mapping[str, float],
) -> tuple[int, float, float, float, str]:
    symbol = str(rec.get("symbol") or "")
    previous_weight = float(previous_lookup.get(symbol, 0.0))
    alpha = _safe_float(rec.get("composite_alpha"))
    liquidity = _safe_float(rec.get("liquidity_20d"))
    return (
        0 if previous_weight > _WEIGHT_TOL else 1,
        -(previous_weight if previous_weight > _WEIGHT_TOL else 0.0),
        -(alpha if alpha is not None else -math.inf),
        -(liquidity if liquidity is not None else -math.inf),
        symbol,
    )


def _issuer_key_for_candidate(rec: Mapping[str, Any]) -> str:
    security = _canonical_issuer_security_name(rec.get("security"))
    if security:
        return security
    return str(rec.get("symbol") or "").strip().upper()


def _canonical_issuer_security_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = _CLASS_SUFFIX_RE.sub(" ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def _select_candidates_with_sector_diversification(
    candidates: List[Dict[str, Any]],
    *,
    target_count: int,
    max_sector_weight: Optional[float],
    relax_sector_cap: bool,
) -> List[Dict[str, Any]]:
    if target_count <= 0:
        return []

    if max_sector_weight is None or max_sector_weight <= 0:
        return candidates[:target_count]

    approx_sector_name_cap = max(1, int(math.ceil(target_count * max_sector_weight)))
    selected: List[Dict[str, Any]] = []
    sector_counts: Dict[str, int] = {}

    for rec in candidates:
        sector = str(rec.get("gics_sector") or "Unknown")
        if sector_counts.get(sector, 0) >= approx_sector_name_cap:
            continue
        selected.append(rec)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        if len(selected) >= target_count:
            break

    if relax_sector_cap and len(selected) < target_count:
        selected_symbols = {str(rec["symbol"]) for rec in selected}
        for rec in candidates:
            sym = str(rec["symbol"])
            if sym in selected_symbols:
                continue
            selected.append(rec)
            selected_symbols.add(sym)
            if len(selected) >= target_count:
                break

    return selected


def _repair_selection_for_capacity(
    candidates: List[Dict[str, Any]],
    selected: List[Dict[str, Any]],
    *,
    target_count: int,
    max_single_weight: Optional[float],
    max_sector_weight: Optional[float],
) -> List[Dict[str, Any]]:
    current = list(selected)
    if len(current) != target_count:
        return current
    if _selection_has_feasible_capacity(current, max_single_weight, max_sector_weight):
        return current

    while True:
        selected_symbols = {str(rec["symbol"]) for rec in current}
        remaining = [rec for rec in candidates if str(rec["symbol"]) not in selected_symbols]
        if not remaining:
            break

        best_feasible_trial: Optional[List[Dict[str, Any]]] = None
        best_feasible_score = -math.inf
        best_partial_trial: Optional[List[Dict[str, Any]]] = None
        best_partial_capacity = -math.inf
        best_partial_score = -math.inf

        for add_rec in remaining:
            add_sym = str(add_rec["symbol"])
            for drop_rec in sorted(current, key=_candidate_sort_key, reverse=True):
                drop_sym = str(drop_rec["symbol"])
                if add_sym == drop_sym:
                    continue
                trial = [rec for rec in current if str(rec["symbol"]) != drop_sym]
                trial.append(add_rec)
                if len({str(rec["symbol"]) for rec in trial}) != target_count:
                    continue

                capacity = _selection_capacity(trial, max_single_weight, max_sector_weight)
                score_sum = sum(float(rec.get("ranking_score", 0.0)) for rec in trial)
                feasible = capacity >= 1.0 - _WEIGHT_TOL
                if feasible:
                    if score_sum > best_feasible_score + _WEIGHT_TOL:
                        best_feasible_trial = trial
                        best_feasible_score = score_sum
                    continue

                if capacity > best_partial_capacity + _WEIGHT_TOL or (
                    abs(capacity - best_partial_capacity) <= _WEIGHT_TOL
                    and score_sum > best_partial_score + _WEIGHT_TOL
                ):
                    best_partial_trial = trial
                    best_partial_capacity = capacity
                    best_partial_score = score_sum

        if best_feasible_trial is not None:
            return sorted(best_feasible_trial, key=_candidate_sort_key)

        if best_partial_trial is None:
            break

        current_capacity = _selection_capacity(current, max_single_weight, max_sector_weight)
        if best_partial_capacity <= current_capacity + _WEIGHT_TOL:
            break
        current = sorted(best_partial_trial, key=_candidate_sort_key)

    if _selection_has_feasible_capacity(current, max_single_weight, max_sector_weight):
        return current

    selected_symbols = {str(rec["symbol"]) for rec in current}
    for rec in candidates:
        sym = str(rec["symbol"])
        if sym in selected_symbols:
            continue
        current.append(rec)
        selected_symbols.add(sym)
        current = sorted(current, key=_candidate_sort_key)
        if _selection_has_feasible_capacity(current, max_single_weight, max_sector_weight):
            return current
    return current


def _apply_incumbent_exit_buffer(
    candidates: List[Dict[str, Any]],
    selected: List[Dict[str, Any]],
    previous_weights: Mapping[str, float],
    *,
    incumbent_exit_rank: Optional[float],
) -> List[Dict[str, Any]]:
    if (
        incumbent_exit_rank is None
        or incumbent_exit_rank <= 0
        or not selected
        or not previous_weights
    ):
        return list(selected)

    rank_limit = min(len(candidates), max(1, int(incumbent_exit_rank)))
    candidate_map = {str(rec["symbol"]): rec for rec in candidates}
    candidate_rank = {str(rec["symbol"]): idx for idx, rec in enumerate(candidates, start=1)}
    buffered_symbols = {str(rec["symbol"]) for rec in selected}

    for rec in candidates[:rank_limit]:
        sym = str(rec["symbol"])
        if sym in buffered_symbols or sym not in previous_weights:
            continue
        buffered_symbols.add(sym)

    if len(buffered_symbols) <= rank_limit:
        return [
            candidate_map[sym]
            for sym in sorted(
                buffered_symbols,
                key=lambda sym: _candidate_sort_key(candidate_map[sym]),
            )
        ]

    protected_symbols = {
        sym for sym in previous_weights if candidate_rank.get(sym, math.inf) <= rank_limit
    }
    removable_symbols = sorted(
        (sym for sym in buffered_symbols if sym not in protected_symbols),
        key=lambda sym: (
            candidate_rank.get(sym, math.inf),
            _candidate_sort_key(candidate_map[sym]),
        ),
        reverse=True,
    )

    for sym in removable_symbols:
        if len(buffered_symbols) <= rank_limit:
            break
        buffered_symbols.remove(sym)

    return [
        candidate_map[sym]
        for sym in sorted(buffered_symbols, key=lambda sym: _candidate_sort_key(candidate_map[sym]))
    ]


def _apply_new_name_cap(
    candidates: List[Dict[str, Any]],
    selected: List[Dict[str, Any]],
    previous_weights: Mapping[str, float],
    *,
    max_new_names_per_rebalance: int,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    cap = max(0, int(max_new_names_per_rebalance or 0))
    meta: Dict[str, Any] = {
        "max_new_names_per_rebalance": cap,
        "new_name_cap_applied": False,
        "deferred_new_names_count": 0,
        "reinstated_previous_names_count": 0,
    }
    if cap <= 0 or not selected or not previous_weights:
        return list(selected), meta

    candidate_map = {str(rec["symbol"]): rec for rec in candidates}
    previous_symbols = {
        str(sym)
        for sym, weight in previous_weights.items()
        if float(weight) > _WEIGHT_TOL and str(sym) in candidate_map
    }
    if not previous_symbols:
        return list(selected), meta

    entrant_symbols = [
        str(rec["symbol"]) for rec in selected if str(rec["symbol"]) not in previous_symbols
    ]
    if len(entrant_symbols) <= cap:
        return list(selected), meta

    allowed_entrants = set(entrant_symbols[:cap])
    adjusted_symbols = {
        str(rec["symbol"])
        for rec in selected
        if str(rec["symbol"]) in previous_symbols or str(rec["symbol"]) in allowed_entrants
    }

    replacement_pool = [
        rec
        for rec in candidates
        if str(rec["symbol"]) in previous_symbols and str(rec["symbol"]) not in adjusted_symbols
    ]
    target_size = len(selected)
    reinstated = 0
    for rec in replacement_pool:
        if len(adjusted_symbols) >= target_size:
            break
        adjusted_symbols.add(str(rec["symbol"]))
        reinstated += 1

    adjusted = [
        candidate_map[sym]
        for sym in sorted(adjusted_symbols, key=lambda sym: _candidate_sort_key(candidate_map[sym]))
    ]
    meta["new_name_cap_applied"] = True
    meta["deferred_new_names_count"] = len(entrant_symbols) - len(allowed_entrants)
    meta["reinstated_previous_names_count"] = reinstated
    return adjusted, meta


def _minimum_feasible_sector_cap(
    selected: List[Dict[str, Any]],
    max_single_weight: Optional[float],
) -> Optional[float]:
    if not selected:
        return None
    if max_single_weight is not None and max_single_weight * len(selected) < 1.0 - _WEIGHT_TOL:
        return None
    if _selection_capacity(selected, max_single_weight, 1.0) < 1.0 - _WEIGHT_TOL:
        return None

    lower = 0.0
    upper = 1.0
    for _ in range(60):
        mid = 0.5 * (lower + upper)
        if _selection_capacity(selected, max_single_weight, mid) >= 1.0 - _WEIGHT_TOL:
            upper = mid
        else:
            lower = mid
    return upper


def _apply_weight_constraints(
    selected: List[Dict[str, Any]],
    raw_preferences: Mapping[str, float],
    *,
    max_single_weight: Optional[float],
    max_sector_weight: Optional[float],
) -> Dict[str, float]:
    if not selected:
        return {}

    symbols = [str(rec["symbol"]) for rec in selected]
    sectors = {str(rec["symbol"]): str(rec.get("gics_sector") or "Unknown") for rec in selected}

    if max_single_weight is not None and max_single_weight * len(symbols) < 1.0 - _WEIGHT_TOL:
        raise ValueError(
            f"max_single_weight={max_single_weight:.4f} infeasible for selected_count={len(symbols)}"
        )
    if max_sector_weight is not None:
        unique_sector_count = len({sectors[sym] for sym in symbols})
        if unique_sector_count * max_sector_weight < 1.0 - _WEIGHT_TOL:
            raise ValueError(
                f"max_sector_weight={max_sector_weight:.4f} infeasible for unique_sectors={unique_sector_count}"
            )

    preferences = _normalize_positive_mapping(raw_preferences, symbols=symbols)
    asset_caps = {
        sym: (max_single_weight if max_single_weight is not None else 1.0) for sym in symbols
    }
    weights = _allocate_mass(preferences, total_mass=1.0, caps=asset_caps)

    if max_sector_weight is not None:
        weights = _apply_sector_caps(
            weights,
            preferences,
            sectors,
            max_sector_weight=max_sector_weight,
            max_single_weight=max_single_weight,
        )

    normalized = _normalize_positive_mapping(weights, symbols=sorted(weights))
    _validate_weight_constraints(
        normalized,
        sectors,
        max_single_weight=max_single_weight,
        max_sector_weight=max_sector_weight,
    )
    return _rounded_weight_mapping(dict(sorted(normalized.items())))


def _apply_turnover_overlay(
    target_weights: Mapping[str, float],
    candidate_map: Mapping[str, Dict[str, Any]],
    previous_weights: Mapping[str, float],
    *,
    turnover_cap: Optional[float],
    max_single_weight: Optional[float],
    max_sector_weight: Optional[float],
) -> tuple[Dict[str, float], Dict[str, Any]]:
    target = {
        str(sym): float(weight)
        for sym, weight in target_weights.items()
        if float(weight) > _WEIGHT_TOL
    }
    meta: Dict[str, Any] = {
        "turnover_cap": turnover_cap,
        "realized_turnover": None,
        "turnover_limited": False,
    }
    if not previous_weights:
        return target, meta

    pre_turnover = _portfolio_turnover(previous_weights, target)
    meta["realized_turnover"] = round(pre_turnover, 8)
    if turnover_cap is None or turnover_cap <= _WEIGHT_TOL:
        return target, meta

    baseline = _project_previous_weights_to_feasible_baseline(
        candidate_map,
        previous_weights,
        max_single_weight=max_single_weight,
        max_sector_weight=max_sector_weight,
    )
    if not baseline:
        logger.info(
            "portfolio_targets: turnover cap skipped because no feasible carryover baseline exists"
        )
        return target, meta

    baseline_turnover = _portfolio_turnover(previous_weights, baseline)
    if baseline_turnover >= turnover_cap - _WEIGHT_TOL:
        meta["realized_turnover"] = round(baseline_turnover, 8)
        meta["turnover_limited"] = True
        return baseline, meta

    residual_budget = turnover_cap - baseline_turnover
    baseline_to_target = _portfolio_turnover(baseline, target)
    if baseline_to_target <= residual_budget + _WEIGHT_TOL:
        meta["realized_turnover"] = round(pre_turnover, 8)
        return target, meta

    blend_ratio = residual_budget / baseline_to_target if baseline_to_target > _WEIGHT_TOL else 1.0
    final_weights = _blend_weight_maps(baseline, target, blend_ratio)
    meta["realized_turnover"] = round(_portfolio_turnover(previous_weights, final_weights), 8)
    meta["turnover_limited"] = True
    return final_weights, meta


def _apply_no_trade_band(
    target_weights: Mapping[str, float],
    candidate_map: Mapping[str, Dict[str, Any]],
    previous_weights: Mapping[str, float],
    *,
    no_trade_band_weight: Optional[float],
    max_single_weight: Optional[float],
    max_sector_weight: Optional[float],
) -> tuple[Dict[str, float], Dict[str, Any]]:
    target = {
        str(sym): float(weight)
        for sym, weight in target_weights.items()
        if float(weight) > _WEIGHT_TOL
    }
    threshold = max(0.0, float(no_trade_band_weight or 0.0))
    meta: Dict[str, Any] = {
        "no_trade_band_weight": threshold,
        "no_trade_band_applied": False,
        "no_trade_band_frozen_names": 0,
        "no_trade_band_frozen_weight": 0.0,
    }
    if threshold <= _WEIGHT_TOL or not previous_weights or not target:
        return target, meta

    frozen = {
        sym: float(previous_weights.get(sym, 0.0))
        for sym in sorted(target)
        if float(previous_weights.get(sym, 0.0)) > _WEIGHT_TOL
        and abs(float(target.get(sym, 0.0)) - float(previous_weights.get(sym, 0.0))) < threshold
    }
    if not frozen:
        return target, meta

    residual_symbols = [sym for sym in sorted(target) if sym not in frozen]
    frozen_total = sum(frozen.values())
    adjusted = dict(frozen)
    if residual_symbols:
        residual_budget = max(0.0, 1.0 - frozen_total)
        residual_target = {sym: float(target.get(sym, 0.0)) for sym in residual_symbols}
        if residual_budget > _WEIGHT_TOL:
            residual_weights = _normalize_positive_mapping(
                residual_target,
                symbols=residual_symbols,
            )
            adjusted.update(
                {
                    sym: residual_budget * float(residual_weights.get(sym, 0.0))
                    for sym in residual_symbols
                }
            )
    adjusted = _rounded_weight_mapping(
        _normalize_positive_mapping(adjusted, symbols=sorted(adjusted))
    )
    sector_by_symbol = {
        str(sym): str((candidate_map.get(sym) or {}).get("gics_sector") or "Unknown")
        for sym in adjusted
    }
    try:
        _validate_weight_constraints(
            adjusted,
            sector_by_symbol,
            max_single_weight=max_single_weight,
            max_sector_weight=max_sector_weight,
        )
    except ValueError:
        meta["no_trade_band_constraint_violation"] = True
        return target, meta

    meta["no_trade_band_applied"] = True
    meta["no_trade_band_frozen_names"] = len(frozen)
    meta["no_trade_band_frozen_weight"] = round(frozen_total, 8)
    return adjusted, meta


def _project_weight_map_to_bounded_simplex(
    target_weights: Mapping[str, float],
    *,
    lower_bounds: Mapping[str, float],
    upper_bounds: Mapping[str, float],
) -> Dict[str, float]:
    symbols = sorted(target_weights)
    if not symbols:
        return {}

    lowers = {sym: max(0.0, float(lower_bounds.get(sym, 0.0))) for sym in symbols}
    uppers = {sym: min(1.0, max(lowers[sym], float(upper_bounds.get(sym, 1.0)))) for sym in symbols}
    lower_sum = sum(lowers.values())
    upper_sum = sum(uppers.values())
    if lower_sum > 1.0 + _WEIGHT_TOL or upper_sum < 1.0 - _WEIGHT_TOL:
        raise ValueError("bounded simplex is infeasible")

    low = -1.0
    high = 1.0
    projected = {sym: float(target_weights.get(sym, 0.0)) for sym in symbols}
    for _ in range(80):
        mid = 0.5 * (low + high)
        projected = {
            sym: min(
                max(float(target_weights.get(sym, 0.0)) - mid, lowers[sym]),
                uppers[sym],
            )
            for sym in symbols
        }
        total = sum(projected.values())
        if abs(total - 1.0) <= 1e-10:
            break
        if total > 1.0:
            low = mid
        else:
            high = mid

    return projected


def _apply_per_name_trade_cap(
    target_weights: Mapping[str, float],
    candidate_map: Mapping[str, Dict[str, Any]],
    previous_weights: Mapping[str, float],
    *,
    per_name_max_trade_weight: Optional[float],
    max_single_weight: Optional[float],
    max_sector_weight: Optional[float],
) -> tuple[Dict[str, float], Dict[str, Any]]:
    target = {
        str(sym): float(weight)
        for sym, weight in target_weights.items()
        if float(weight) > _WEIGHT_TOL
    }
    threshold = max(0.0, float(per_name_max_trade_weight or 0.0))
    meta: Dict[str, Any] = {
        "per_name_max_trade_weight": threshold,
        "per_name_max_trade_applied": False,
        "per_name_max_trade_clipped_names": 0,
        "per_name_max_trade_clipped_weight": 0.0,
    }
    if threshold <= _WEIGHT_TOL or not previous_weights or not target:
        return target, meta

    survivors = {
        sym: float(previous_weights.get(sym, 0.0))
        for sym in sorted(target)
        if float(previous_weights.get(sym, 0.0)) > _WEIGHT_TOL
    }
    if not survivors:
        return target, meta

    lower_bounds = {sym: 0.0 for sym in target}
    upper_bounds = {sym: 1.0 for sym in target}
    clipped_symbols: set[str] = set()
    clipped_weight = 0.0
    for sym, prev_weight in survivors.items():
        lower_bounds[sym] = max(0.0, prev_weight - threshold)
        upper_bounds[sym] = min(1.0, prev_weight + threshold)
        delta = abs(float(target.get(sym, 0.0)) - prev_weight)
        if delta > threshold + _WEIGHT_TOL:
            clipped_symbols.add(sym)
            clipped_weight += 0.5 * delta
    if not clipped_symbols:
        return target, meta

    try:
        adjusted = _project_weight_map_to_bounded_simplex(
            target,
            lower_bounds=lower_bounds,
            upper_bounds=upper_bounds,
        )
    except ValueError:
        meta["per_name_max_trade_infeasible"] = True
        return target, meta

    adjusted = _rounded_weight_mapping(
        _normalize_positive_mapping(adjusted, symbols=sorted(adjusted))
    )
    sector_by_symbol = {
        str(sym): str((candidate_map.get(sym) or {}).get("gics_sector") or "Unknown")
        for sym in adjusted
    }
    try:
        _validate_weight_constraints(
            adjusted,
            sector_by_symbol,
            max_single_weight=max_single_weight,
            max_sector_weight=max_sector_weight,
        )
    except ValueError:
        meta["per_name_max_trade_constraint_violation"] = True
        return target, meta

    meta["per_name_max_trade_applied"] = True
    meta["per_name_max_trade_clipped_names"] = len(clipped_symbols)
    meta["per_name_max_trade_clipped_weight"] = round(clipped_weight, 8)
    return adjusted, meta


def _apply_min_target_weight_floor(
    target_weights: Mapping[str, float],
    candidate_map: Mapping[str, Dict[str, Any]],
    previous_weights: Mapping[str, float],
    *,
    min_target_weight: float,
    min_names: int,
    max_single_weight: Optional[float],
    max_sector_weight: Optional[float],
    turnover_meta: Mapping[str, Any],
) -> tuple[Dict[str, float], Dict[str, Any]]:
    threshold = max(0.0, float(min_target_weight))
    current = {
        str(sym): float(weight)
        for sym, weight in target_weights.items()
        if str(sym) in candidate_map and float(weight) > _WEIGHT_TOL
    }
    meta = dict(turnover_meta or {})
    if threshold <= _WEIGHT_TOL or len(current) <= max(1, int(min_names)):
        return current, meta

    for _ in range(len(current)):
        below_floor = {
            sym for sym, weight in current.items() if float(weight) < threshold - _WEIGHT_TOL
        }
        if not below_floor:
            break

        ordered = sorted(
            current,
            key=lambda sym: (
                -float(current[sym]),
                _candidate_sort_key(candidate_map[sym]),
            ),
        )
        keep_count = max(max(1, int(min_names)), len(current) - len(below_floor))
        survivors = ordered[:keep_count]
        raw_preferences = {sym: float(current[sym]) for sym in survivors}
        selected = [candidate_map[sym] for sym in survivors]
        try:
            current = _apply_weight_constraints(
                selected,
                raw_preferences,
                max_single_weight=max_single_weight,
                max_sector_weight=max_sector_weight,
            )
        except ValueError:
            return {
                str(sym): float(weight)
                for sym, weight in target_weights.items()
                if float(weight) > _WEIGHT_TOL
            }, meta

    pruned = _rounded_weight_mapping(current)
    if set(pruned) != set(target_weights):
        logger.info(
            "portfolio_targets: min_target_weight floor pruned names threshold=%.4f dropped=%d remaining=%d",
            threshold,
            max(0, len(target_weights) - len(pruned)),
            len(pruned),
        )
        meta["realized_turnover"] = round(
            _portfolio_turnover(previous_weights, pruned),
            8,
        )
    return pruned, meta


def _project_previous_weights_to_feasible_baseline(
    candidate_map: Mapping[str, Dict[str, Any]],
    previous_weights: Mapping[str, float],
    *,
    max_single_weight: Optional[float],
    max_sector_weight: Optional[float],
) -> Dict[str, float]:
    carryover_candidates = [candidate_map[sym] for sym in previous_weights if sym in candidate_map]
    if not carryover_candidates:
        return {}

    raw_preferences = {
        str(rec["symbol"]): previous_weights[str(rec["symbol"])] for rec in carryover_candidates
    }
    try:
        return _apply_weight_constraints(
            carryover_candidates,
            raw_preferences,
            max_single_weight=max_single_weight,
            max_sector_weight=max_sector_weight,
        )
    except ValueError:
        return {}


def _blend_weight_maps(
    baseline_weights: Mapping[str, float],
    target_weights: Mapping[str, float],
    ratio: float,
) -> Dict[str, float]:
    lam = min(max(float(ratio), 0.0), 1.0)
    symbols = sorted(set(baseline_weights) | set(target_weights))
    blended = {
        sym: (1.0 - lam) * float(baseline_weights.get(sym, 0.0))
        + lam * float(target_weights.get(sym, 0.0))
        for sym in symbols
    }
    normalized = _normalize_positive_mapping(blended, symbols=symbols)
    return _rounded_weight_mapping(normalized)


def _portfolio_turnover(
    previous_weights: Mapping[str, float],
    target_weights: Mapping[str, float],
) -> float:
    symbols = set(previous_weights) | set(target_weights)
    if not symbols:
        return 0.0
    total_abs = sum(
        abs(float(target_weights.get(sym, 0.0)) - float(previous_weights.get(sym, 0.0)))
        for sym in symbols
    )
    return 0.5 * total_abs


def _normalize_previous_positions(
    previous_positions: Optional[List[Dict[str, Any]]],
) -> Dict[str, float]:
    if not previous_positions:
        return {}

    weights: Dict[str, float] = {}
    for rec in previous_positions:
        sym = str(rec.get("symbol") or "").strip()
        weight = _safe_float(rec.get("target_weight"))
        if not sym or weight is None or weight <= _WEIGHT_TOL:
            continue
        weights[sym] = weights.get(sym, 0.0) + weight

    if not weights:
        return {}
    return _normalize_positive_mapping(weights, symbols=sorted(weights))


def _apply_sector_caps(
    weights: Mapping[str, float],
    base_preferences: Mapping[str, float],
    sector_by_symbol: Mapping[str, str],
    *,
    max_sector_weight: float,
    max_single_weight: Optional[float],
    max_iter: int = 8,
) -> Dict[str, float]:
    current = dict(weights)
    symbols_by_sector = _symbols_by_sector(sector_by_symbol)

    for _ in range(max_iter):
        current = _normalize_positive_mapping(current, symbols=list(current))
        sector_sums = _sector_weight_sums(current, sector_by_symbol)
        over_cap = {
            sector: total
            for sector, total in sector_sums.items()
            if total > max_sector_weight + _WEIGHT_TOL
        }
        if not over_cap:
            return current

        excess = 0.0
        for sector, total in over_cap.items():
            scale = max_sector_weight / total
            for sym in symbols_by_sector.get(sector, []):
                current[sym] *= scale
            excess += total - max_sector_weight

        if excess <= _WEIGHT_TOL:
            return _normalize_positive_mapping(current, symbols=list(current))

        updated_sector_sums = _sector_weight_sums(current, sector_by_symbol)
        sector_caps = {
            sector: min(
                max_sector_weight - updated_sector_sums.get(sector, 0.0),
                sum(
                    _asset_remaining_cap(current, sym, max_single_weight)
                    for sym in symbols_by_sector.get(sector, [])
                ),
            )
            for sector in symbols_by_sector
            if updated_sector_sums.get(sector, 0.0) < max_sector_weight - _WEIGHT_TOL
        }
        if not sector_caps:
            raise ValueError("sector cap exhausted all available receiving sectors")

        sector_preferences = {}
        for sector, members in symbols_by_sector.items():
            if sector not in sector_caps:
                continue
            pref = sum(
                max(base_preferences.get(sym, 0.0), 0.0)
                for sym in members
                if _asset_remaining_cap(current, sym, max_single_weight) > _WEIGHT_TOL
            )
            sector_preferences[sector] = pref

        sector_add = _allocate_mass(
            sector_preferences,
            total_mass=excess,
            caps=sector_caps,
        )

        allocated_total = 0.0
        for sector, add_mass in sector_add.items():
            if add_mass <= _WEIGHT_TOL:
                continue
            members = [
                sym
                for sym in symbols_by_sector.get(sector, [])
                if _asset_remaining_cap(current, sym, max_single_weight) > _WEIGHT_TOL
            ]
            if not members:
                continue
            member_prefs = {sym: max(base_preferences.get(sym, 0.0), 0.0) for sym in members}
            member_caps = {
                sym: _asset_remaining_cap(current, sym, max_single_weight) for sym in members
            }
            member_add = _allocate_mass(
                member_prefs,
                total_mass=add_mass,
                caps=member_caps,
            )
            for sym, delta in member_add.items():
                current[sym] += delta
                allocated_total += delta

        if allocated_total + _WEIGHT_TOL < excess:
            raise ValueError(
                "unable to redistribute excess weight under sector and single-name caps"
            )

    raise ValueError("sector cap iteration did not converge")


def _allocate_mass(
    preferences: Mapping[str, float],
    *,
    total_mass: float,
    caps: Mapping[str, float],
) -> Dict[str, float]:
    if total_mass <= _WEIGHT_TOL:
        return {str(key): 0.0 for key in preferences}

    active = {
        str(key): max(0.0, float(caps.get(key, 0.0)))
        for key in preferences
        if caps.get(key, 0.0) is not None and float(caps.get(key, 0.0)) > _WEIGHT_TOL
    }
    if not active:
        raise ValueError("no capacity available for mass allocation")

    if sum(active.values()) + _WEIGHT_TOL < total_mass:
        raise ValueError("allocation infeasible: capacity below required total mass")

    pref = {key: max(0.0, float(preferences.get(key, 0.0))) for key in active}
    alloc = {key: 0.0 for key in active}
    remaining_mass = float(total_mass)
    free_keys = set(active)

    while free_keys and remaining_mass > _WEIGHT_TOL:
        pref_total = sum(pref[key] for key in free_keys)
        if pref_total <= _WEIGHT_TOL:
            proposal = {key: remaining_mass / len(free_keys) for key in free_keys}
        else:
            proposal = {key: remaining_mass * pref[key] / pref_total for key in free_keys}

        saturated = [key for key, value in proposal.items() if value > active[key] + _WEIGHT_TOL]
        if not saturated:
            for key, value in proposal.items():
                alloc[key] += value
            remaining_mass = 0.0
            break

        for key in saturated:
            alloc[key] += active[key]
            remaining_mass -= active[key]
            free_keys.remove(key)

    if remaining_mass > _WEIGHT_TOL:
        raise ValueError("allocation did not converge")

    return alloc


def _normalize_positive_mapping(
    values: Mapping[str, float],
    *,
    symbols: Optional[List[str]] = None,
) -> Dict[str, float]:
    keys = symbols or [str(key) for key in values]
    out = {str(key): max(0.0, float(values.get(key, 0.0))) for key in keys}
    total = sum(out.values())
    if total <= _WEIGHT_TOL:
        equal = 1.0 / len(out)
        return {key: equal for key in out}
    return {key: value / total for key, value in out.items()}


def _symbols_by_sector(sector_by_symbol: Mapping[str, str]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for sym, sector in sector_by_symbol.items():
        out.setdefault(str(sector), []).append(str(sym))
    return out


def _sector_weight_sums(
    weights: Mapping[str, float],
    sector_by_symbol: Mapping[str, str],
) -> Dict[str, float]:
    sums: Dict[str, float] = {}
    for sym, weight in weights.items():
        sector = str(sector_by_symbol.get(sym) or "Unknown")
        sums[sector] = sums.get(sector, 0.0) + float(weight)
    return sums


def _asset_remaining_cap(
    current: Mapping[str, float],
    symbol: str,
    max_single_weight: Optional[float],
) -> float:
    current_weight = float(current.get(symbol, 0.0))
    if max_single_weight is None:
        return max(0.0, 1.0 - current_weight)
    return max(0.0, max_single_weight - current_weight)


def _validate_weight_constraints(
    weights: Mapping[str, float],
    sector_by_symbol: Mapping[str, str],
    *,
    max_single_weight: Optional[float],
    max_sector_weight: Optional[float],
) -> None:
    total_weight = sum(float(weight) for weight in weights.values())
    if abs(total_weight - 1.0) > 1e-8:
        raise ValueError(f"final weights do not sum to 1.0: total={total_weight:.10f}")

    if max_single_weight is not None:
        offenders = [
            (sym, float(weight))
            for sym, weight in weights.items()
            if float(weight) > max_single_weight + 1e-8
        ]
        if offenders:
            sym, weight = offenders[0]
            raise ValueError(
                f"single-name cap violated after allocation: symbol={sym} weight={weight:.10f} cap={max_single_weight:.10f}"
            )

    if max_sector_weight is not None:
        sector_sums = _sector_weight_sums(weights, sector_by_symbol)
        offenders = [
            (sector, total)
            for sector, total in sector_sums.items()
            if float(total) > max_sector_weight + 1e-8
        ]
        if offenders:
            sector, total = offenders[0]
            raise ValueError(
                f"sector cap violated after allocation: sector={sector} total={total:.10f} cap={max_sector_weight:.10f}"
            )


def _signal_value(record: Mapping[str, Any], signal_field: str) -> float:
    value = _safe_float(record.get(signal_field))
    if value is not None:
        return value
    fallback = _safe_float(record.get("composite_alpha"))
    return fallback if fallback is not None else 0.0


def _zscore_signal(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values
    mean = float(np.mean(values))
    std = float(np.std(values))
    if std <= _WEIGHT_TOL:
        return np.zeros_like(values, dtype=float)
    return (values - mean) / std


def _transform_optimizer_signal(
    values: np.ndarray,
    *,
    method: str,
    clip: float,
) -> np.ndarray:
    if values.size == 0:
        return values

    method_name = str(method or "clipped_zscore").strip().lower()
    if method_name == "rank":
        if values.size == 1:
            return np.zeros_like(values, dtype=float)
        ranks = pd.Series(values).rank(method="average").to_numpy(dtype=float)
        rank_pct = (ranks - 1.0) / max(1.0, float(values.size - 1))
        return 2.0 * (rank_pct - 0.5)

    z = _zscore_signal(values)
    if method_name == "zscore":
        return z

    clipped = np.clip(z, -float(clip), float(clip))
    scale = max(float(clip), 1.0)
    return clipped / scale


def _anchor_weight_vector(
    candidates: List[Dict[str, Any]],
    risk_lookup: Mapping[str, Dict[str, Any]],
    *,
    anchor_scheme: str,
    max_single_weight: Optional[float],
    max_sector_weight: Optional[float],
) -> Optional[np.ndarray]:
    scheme_name = str(anchor_scheme or "equal").strip().lower()
    scheme = _WEIGHTING_SCHEME_REGISTRY.get(scheme_name)
    if scheme is None or scheme.name == MeanVarianceScheme.name:
        scheme = EqualWeightScheme()

    seed_scheme = scheme.compute_raw_weights(
        candidates,
        risk_lookup,
    )
    try:
        constrained = _apply_weight_constraints(
            candidates,
            seed_scheme.raw_weights,
            max_single_weight=max_single_weight,
            max_sector_weight=max_sector_weight,
        )
    except ValueError:
        if scheme.name != EqualWeightScheme.name:
            fallback = EqualWeightScheme().compute_raw_weights(candidates, risk_lookup)
            try:
                constrained = _apply_weight_constraints(
                    candidates,
                    fallback.raw_weights,
                    max_single_weight=max_single_weight,
                    max_sector_weight=max_sector_weight,
                )
            except ValueError:
                return None
        else:
            return None

    ordered = [str(rec["symbol"]) for rec in candidates]
    return np.array([float(constrained.get(sym, 0.0)) for sym in ordered], dtype=float)


def _reference_weight_vector(
    symbols: List[str],
    reference_weights: Optional[Mapping[str, float]],
) -> Optional[np.ndarray]:
    if not symbols or not reference_weights:
        return None
    normalized = _normalize_positive_mapping(reference_weights, symbols=symbols)
    if not any(float(normalized.get(sym, 0.0)) > _WEIGHT_TOL for sym in symbols):
        return None
    return np.array([normalized[sym] for sym in symbols], dtype=float)


def _active_weight_bounds(
    anchor_weights: np.ndarray,
    caps: np.ndarray,
    *,
    max_active_overweight: Optional[float],
    max_active_underweight: Optional[float],
) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    if anchor_weights.shape != caps.shape:
        return None, None

    lower_bounds = np.zeros_like(anchor_weights, dtype=float)
    upper_bounds = np.minimum(caps.astype(float), np.ones_like(caps, dtype=float))

    if max_active_underweight is not None:
        lower_bounds = np.maximum(
            lower_bounds,
            anchor_weights - float(max_active_underweight),
        )
    if max_active_overweight is not None:
        upper_bounds = np.minimum(
            upper_bounds,
            anchor_weights + float(max_active_overweight),
        )

    lower_bounds = np.clip(lower_bounds, 0.0, None)
    upper_bounds = np.maximum(upper_bounds, lower_bounds)
    if float(np.sum(lower_bounds)) > 1.0 + 1e-8:
        return None, None
    if float(np.sum(upper_bounds)) < 1.0 - 1e-8:
        return None, None
    return lower_bounds, upper_bounds


def _optimizer_breadth_floor(
    *,
    min_target_weight: Optional[float],
    max_single_weight: Optional[float],
) -> float:
    configured_floor = float(min_target_weight or 0.0)
    if configured_floor > _WEIGHT_TOL:
        return configured_floor
    if max_single_weight is not None and max_single_weight > _WEIGHT_TOL:
        return min(0.001, max_single_weight / 50.0)
    return 0.001


def _stabilize_optimizer_breadth(
    optimized: np.ndarray,
    initial_weights: np.ndarray,
    *,
    min_active_names: int,
    min_weight_floor: float,
) -> np.ndarray:
    if (
        optimized.size == 0
        or initial_weights.shape != optimized.shape
        or min_active_names <= 0
        or min_weight_floor <= _WEIGHT_TOL
    ):
        return optimized

    active_count = int(np.sum(optimized >= min_weight_floor - _WEIGHT_TOL))
    if active_count >= min_active_names:
        return optimized

    required = min(int(min_active_names), int(optimized.size))
    eta = 0.0
    for idx in list(np.argsort(-initial_weights))[:required]:
        current_weight = float(optimized[idx])
        seed_weight = float(initial_weights[idx])
        if current_weight >= min_weight_floor - _WEIGHT_TOL:
            continue
        if seed_weight <= current_weight + _WEIGHT_TOL:
            continue
        required_eta = (min_weight_floor - current_weight) / (seed_weight - current_weight)
        eta = max(eta, required_eta)

    eta = min(max(eta, 0.0), 1.0)
    if eta <= _WEIGHT_TOL:
        return optimized

    blended = (1.0 - eta) * optimized + eta * initial_weights
    total = float(np.sum(blended))
    if total <= _WEIGHT_TOL:
        return optimized
    return blended / total


def _build_candidate_covariance_matrix(
    symbols: List[str],
    covariance_matrix: Any,
    risk_lookup: Mapping[str, Dict[str, Any]],
) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame()

    cov = pd.DataFrame()
    if isinstance(covariance_matrix, pd.DataFrame) and not covariance_matrix.empty:
        cov = covariance_matrix.copy()
        cov.index = [str(idx) for idx in cov.index]
        cov.columns = [str(col) for col in cov.columns]
        cov = cov.apply(pd.to_numeric, errors="coerce")

    variances: List[float] = []
    if not cov.empty:
        variances.extend(
            float(val)
            for val in np.diag(cov.to_numpy(dtype=float))
            if math.isfinite(float(val)) and float(val) > 0
        )
    for sym in symbols:
        fallback_var = _fallback_daily_variance(sym, risk_lookup)
        if fallback_var is not None:
            variances.append(fallback_var)
    fallback_var = _median(variances) if variances else (0.20**2) / 252.0

    mat = np.zeros((len(symbols), len(symbols)), dtype=float)
    for i, sym_i in enumerate(symbols):
        for j, sym_j in enumerate(symbols):
            if not cov.empty and sym_i in cov.index and sym_j in cov.columns:
                value = _safe_float(cov.loc[sym_i, sym_j])
                if value is not None:
                    mat[i, j] = value
                    continue
            if i == j:
                diag_value = _fallback_daily_variance(sym_i, risk_lookup)
                mat[i, j] = diag_value if diag_value is not None else fallback_var

    mat = 0.5 * (mat + mat.T)
    diag = np.diag(mat).copy()
    diag = np.where(diag > _WEIGHT_TOL, diag, fallback_var)
    np.fill_diagonal(mat, diag)
    mat = _nearest_psd(mat)

    return pd.DataFrame(mat, index=symbols, columns=symbols)


def _fallback_daily_variance(
    symbol: str,
    risk_lookup: Mapping[str, Dict[str, Any]],
) -> Optional[float]:
    ann_vol = _safe_float(risk_lookup.get(symbol, {}).get("volatility_60d"))
    if ann_vol is None or ann_vol <= 0:
        return None
    return (ann_vol**2) / 252.0


def _coerce_portfolio_as_of_date(
    records: List[Dict[str, Any]],
) -> Optional[date]:
    for record in records:
        value = record.get("as_of_date")
        if value is None:
            continue
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value).strip()
        if not text:
            continue
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            continue
    return None


def _load_historical_composite_alpha(
    *,
    as_of_date: date,
    symbols: List[str],
    max_lookback_days: int,
) -> Dict[str, List[tuple[date, float]]]:  # pragma: no cover - integration DB adapter
    if not symbols:
        return {}

    from sqlalchemy import text
    from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine

    start_date = as_of_date - timedelta(days=max_lookback_days)
    sql = text("""
        SELECT as_of_date, symbol, composite_alpha
        FROM systematic_equity.feature_factor_scores
        WHERE as_of_date < :as_of_date
          AND as_of_date >= :start_date
          AND symbol = ANY(:symbols)
          AND composite_alpha IS NOT NULL
        ORDER BY as_of_date ASC
        """)
    history: Dict[str, List[tuple[date, float]]] = {sym: [] for sym in symbols}
    engine = get_db_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            sql,
            {
                "as_of_date": as_of_date,
                "start_date": start_date,
                "symbols": list(symbols),
            },
        ).mappings()
        for row in rows:
            symbol = str(row.get("symbol") or "").strip()
            obs_date = row.get("as_of_date")
            alpha = _safe_float(row.get("composite_alpha"))
            if not symbol or alpha is None:
                continue
            if isinstance(obs_date, datetime):
                resolved_date = obs_date.date()
            elif isinstance(obs_date, date):
                resolved_date = obs_date
            else:
                text_value = str(obs_date or "").strip()
                if not text_value:
                    continue
                try:
                    resolved_date = date.fromisoformat(text_value[:10])
                except ValueError:
                    continue
            history.setdefault(symbol, []).append((resolved_date, alpha))
    return history


def _nearest_psd(matrix: np.ndarray) -> np.ndarray:
    symmetric = 0.5 * (matrix + matrix.T)
    eigvals, eigvecs = np.linalg.eigh(symmetric)
    eigvals = np.clip(eigvals, 1e-10, None)
    psd = eigvecs @ np.diag(eigvals) @ eigvecs.T
    psd = 0.5 * (psd + psd.T)
    return psd


def _solve_mean_variance_weights(
    expected_returns: np.ndarray,
    covariance: np.ndarray,
    caps: np.ndarray,
    *,
    risk_aversion: float,
    ridge_penalty: float,
    turnover_penalty: float,
    reference_weights: Optional[np.ndarray],
    anchor_weights: np.ndarray,
    use_active_risk: bool,
    max_iter: int,
    tolerance: float,
    configured_step_size: Optional[float],
    initial_weights: np.ndarray,
    lower_bounds: Optional[np.ndarray],
    upper_bounds: Optional[np.ndarray],
) -> Optional[np.ndarray]:
    if expected_returns.size == 0:
        return None
    if covariance.shape != (expected_returns.size, expected_returns.size):
        return None
    if caps.shape != expected_returns.shape:
        return None
    if float(caps.sum()) < 1.0 - _WEIGHT_TOL:
        return None
    if anchor_weights.shape != expected_returns.shape:
        return None
    if reference_weights is not None and reference_weights.shape != expected_returns.shape:
        return None
    if lower_bounds is not None and lower_bounds.shape != expected_returns.shape:
        return None
    if upper_bounds is not None and upper_bounds.shape != expected_returns.shape:
        return None

    lower = (
        lower_bounds.astype(float)
        if lower_bounds is not None
        else np.zeros_like(expected_returns, dtype=float)
    )
    upper = upper_bounds.astype(float) if upper_bounds is not None else caps.astype(float)

    anchor = _project_to_bounded_simplex(anchor_weights, lower, upper)
    if anchor is None:
        return None

    w = _project_to_bounded_simplex(initial_weights, lower, upper)
    if w is None:
        w = anchor.copy()

    n_assets = len(expected_returns)
    identity = np.eye(n_assets)
    penalty_matrix = np.zeros((n_assets, n_assets), dtype=float)
    linear_term = expected_returns.astype(float).copy()

    if risk_aversion > _WEIGHT_TOL:
        penalty_matrix = penalty_matrix + float(risk_aversion) * covariance
        if use_active_risk:
            linear_term = linear_term + float(risk_aversion) * (covariance @ anchor)

    if ridge_penalty > _WEIGHT_TOL:
        penalty_matrix = penalty_matrix + float(ridge_penalty) * identity
        linear_term = linear_term + float(ridge_penalty) * anchor

    if reference_weights is not None and turnover_penalty > _WEIGHT_TOL:
        penalty_matrix = penalty_matrix + float(turnover_penalty) * identity
        linear_term = linear_term + float(turnover_penalty) * reference_weights

    max_eig = float(np.max(np.linalg.eigvalsh(penalty_matrix))) if n_assets else 0.0
    if not math.isfinite(max_eig) or max_eig <= _WEIGHT_TOL:
        max_eig = 1.0
    step_size = (
        configured_step_size
        if configured_step_size is not None and configured_step_size > 0
        else 1.0 / max_eig
    )

    for _ in range(max_iter):
        grad = linear_term - (penalty_matrix @ w)
        updated = _project_to_bounded_simplex(w + step_size * grad, lower, upper)
        if updated is None:
            return None
        if float(np.linalg.norm(updated - w, ord=1)) <= tolerance:
            return updated
        w = updated
    return w


def _project_to_bounded_simplex(
    vector: np.ndarray,
    lower_bounds: np.ndarray,
    upper_bounds: np.ndarray,
    *,
    total_weight: float = 1.0,
) -> Optional[np.ndarray]:
    if vector.size == 0 or lower_bounds.shape != vector.shape or upper_bounds.shape != vector.shape:
        return None

    lower = np.clip(lower_bounds.astype(float), 0.0, None)
    upper = np.maximum(upper_bounds.astype(float), lower)
    lower_sum = float(np.sum(lower))
    upper_sum = float(np.sum(upper))
    if lower_sum > total_weight + 1e-8:
        return None
    if upper_sum < total_weight - 1e-8:
        return None

    residual_total = total_weight - lower_sum
    if residual_total <= _WEIGHT_TOL:
        return lower.copy()

    residual_caps = upper - lower
    shifted = vector - lower
    projected = _project_to_capped_simplex(
        shifted,
        residual_caps,
        total_weight=residual_total,
    )
    if projected is None:
        return None
    return lower + projected


def _project_to_capped_simplex(
    vector: np.ndarray,
    caps: np.ndarray,
    *,
    total_weight: float = 1.0,
    max_iter: int = 80,
) -> Optional[np.ndarray]:
    if vector.size == 0 or caps.size != vector.size:
        return None
    if float(caps.sum()) < total_weight - _WEIGHT_TOL:
        return None

    lower = float(np.min(vector - caps))
    upper = float(np.max(vector))
    for _ in range(max_iter):
        tau = 0.5 * (lower + upper)
        projected = np.clip(vector - tau, 0.0, caps)
        total = float(projected.sum())
        if abs(total - total_weight) <= 1e-10:
            break
        if total > total_weight:
            lower = tau
        else:
            upper = tau

    projected = np.clip(vector - upper, 0.0, caps)
    total = float(projected.sum())
    if total <= _WEIGHT_TOL:
        return None
    projected /= total
    clipped = np.minimum(projected, caps)
    residual = total_weight - float(clipped.sum())
    if residual > 1e-10:
        remaining = caps - clipped
        room = float(remaining.sum())
        if room <= _WEIGHT_TOL:
            return None
        clipped += residual * np.clip(remaining, 0.0, None) / room
    return clipped


def _safe_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _median(values: List[float]) -> float:
    ordered = sorted(float(v) for v in values if math.isfinite(float(v)))
    if not ordered:
        return 1.0
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _selection_has_feasible_capacity(
    selected: List[Dict[str, Any]],
    max_single_weight: Optional[float],
    max_sector_weight: Optional[float],
) -> bool:
    return _selection_capacity(selected, max_single_weight, max_sector_weight) >= 1.0 - _WEIGHT_TOL


def _selection_capacity(
    selected: List[Dict[str, Any]],
    max_single_weight: Optional[float],
    max_sector_weight: Optional[float],
) -> float:
    if not selected:
        return 0.0
    if max_single_weight is not None and max_single_weight * len(selected) < 1.0 - _WEIGHT_TOL:
        return 0.0
    if max_sector_weight is None:
        return 1.0

    sector_counts: Dict[str, int] = {}
    for rec in selected:
        sector = str(rec.get("gics_sector") or "Unknown")
        sector_counts[sector] = sector_counts.get(sector, 0) + 1

    total_capacity = 0.0
    for count in sector_counts.values():
        if max_single_weight is None:
            sector_capacity = max_sector_weight
        else:
            sector_capacity = min(max_sector_weight, count * max_single_weight)
        total_capacity += sector_capacity
    return total_capacity
