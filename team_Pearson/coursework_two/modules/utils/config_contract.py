from __future__ import annotations

"""Cross-CW1/CW2 configuration contract checks.

CW1 owns the broader upstream collection scope. CW2 may narrow that scope for
the final investable universe and portfolio backtest, but should not silently
drift away from shared operating assumptions such as the benchmark ticker.
"""

import math
from typing import Any, Dict, Iterable, List, Optional

_DEFAULT_SHARED_BENCHMARK = "SPY"
_TRADING_DAYS_PER_YEAR = 252
_MIN_RECOMMENDED_WARMUP_DAYS = 252


def validate_shared_runtime_contract(
    cw1_cfg: Dict[str, Any],
    cw2_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate shared CW1/CW2 runtime assumptions.

    Returns a normalized contract summary. Raises ``ValueError`` when the two
    configuration files express incompatible semantics.
    """

    cw1_benchmark = _normalize_ticker((cw1_cfg.get("market_factors") or {}).get("benchmark_ticker"))
    cw2_bt_cfg = dict(cw2_cfg.get("backtest") or {})
    cw2_benchmark_raw = cw2_bt_cfg.get("benchmark_ticker")
    cw2_benchmark = _normalize_ticker(cw2_benchmark_raw, default=cw1_benchmark)
    if cw2_benchmark != cw1_benchmark:
        raise ValueError(
            "CW2 backtest benchmark_ticker must match CW1 market_factors.benchmark_ticker "
            f"(cw1={cw1_benchmark}, cw2={cw2_benchmark}). "
            "Use backtest.analysis.secondary_benchmark for additional comparison series."
        )

    upstream_allowlist = _normalize_allowlist(
        (cw1_cfg.get("universe") or {}).get("country_allowlist")
    )
    investable_allowlist = _normalize_allowlist(
        (cw2_cfg.get("investable_universe") or {}).get("country_allowlist")
    )
    effective_investable_allowlist = investable_allowlist or upstream_allowlist
    if upstream_allowlist is not None and effective_investable_allowlist is not None:
        extra_countries = sorted(set(effective_investable_allowlist) - set(upstream_allowlist))
        if extra_countries:
            raise ValueError(
                "CW2 investable_universe.country_allowlist must be a subset of "
                "CW1 universe.country_allowlist "
                f"(outside parent scope: {', '.join(extra_countries)})."
            )

    return {
        "shared_benchmark_ticker": cw1_benchmark,
        "cw1_upstream_country_allowlist": upstream_allowlist,
        "cw2_investable_country_allowlist": investable_allowlist,
        "effective_investable_country_allowlist": effective_investable_allowlist,
    }


def evaluate_upstream_history_contract(
    cw1_cfg: Dict[str, Any],
    cw2_cfg: Dict[str, Any],
    *,
    effective_backfill_years: Optional[int] = None,
) -> Dict[str, Any]:
    """Evaluate whether a CW1 upstream run is deep enough for the CW2 window.

    Hard requirement:
    - CW1 backfill must cover at least the CW2 backtest window.

    Advisory:
    - A warm-up buffer is recommended so the earliest CW2 dates have stable
      rolling factor / covariance inputs.
    """

    pipeline_cfg = dict(cw1_cfg.get("pipeline") or {})
    bt_cfg = dict(cw2_cfg.get("backtest") or {})
    effective_years = int(
        effective_backfill_years
        if effective_backfill_years is not None
        else pipeline_cfg.get("backfill_years", 5)
    )
    lookback_years = int(bt_cfg.get("lookback_years", 5))

    if effective_years < lookback_years:
        raise ValueError(
            "CW1 upstream backfill window must be at least as large as the CW2 "
            f"backtest window (cw1_backfill_years={effective_years}, "
            f"cw2_lookback_years={lookback_years})."
        )

    warmup_days = _recommended_warmup_days(cw1_cfg, cw2_cfg)
    recommended_buffer_years = max(1, math.ceil(warmup_days / _TRADING_DAYS_PER_YEAR))
    recommended_years = lookback_years + recommended_buffer_years

    warning: Optional[str] = None
    if effective_years < recommended_years:
        warning = (
            "CW1 upstream backfill matches the CW2 window but leaves little warm-up "
            f"buffer for rolling features. Recommended backfill_years >= {recommended_years} "
            f"(current={effective_years}, cw2_lookback_years={lookback_years}, "
            f"warmup_days={warmup_days})."
        )

    return {
        "cw1_backfill_years": effective_years,
        "cw2_lookback_years": lookback_years,
        "recommended_warmup_days": warmup_days,
        "recommended_buffer_years": recommended_buffer_years,
        "recommended_backfill_years": recommended_years,
        "warning": warning,
    }


def _recommended_warmup_days(
    cw1_cfg: Dict[str, Any],
    cw2_cfg: Dict[str, Any],
) -> int:
    market_cfg = dict(cw1_cfg.get("market_factors") or {})
    portfolio_cov_cfg = dict(
        ((cw2_cfg.get("portfolio_construction") or {}).get("covariance") or {})
    )
    regime_cfg = dict(cw2_cfg.get("regime") or {})
    intraday_cfg = dict(((cw2_cfg.get("backtest") or {}).get("intraday_triggers") or {}))

    return max(
        _MIN_RECOMMENDED_WARMUP_DAYS,
        int(market_cfg.get("beta_window_days", _MIN_RECOMMENDED_WARMUP_DAYS)),
        int(portfolio_cov_cfg.get("lookback_days", _MIN_RECOMMENDED_WARMUP_DAYS)),
        int(regime_cfg.get("history_lookback_days", 0)),
        int(intraday_cfg.get("stop_loss_vol_lookback_days", 0)),
    )


def _normalize_allowlist(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        items: Iterable[Any] = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        items = value
    else:
        raise ValueError(
            "country_allowlist must be null, a comma-separated string, or a list of country codes."
        )

    normalized = sorted(
        {
            str(item).strip().upper()
            for item in items
            if str(item).strip() and str(item).strip().upper() not in {"ALL", "ANY", "*"}
        }
    )
    return normalized or None


def _normalize_ticker(value: Any, *, default: str = _DEFAULT_SHARED_BENCHMARK) -> str:
    text = str(value).strip().upper() if value is not None else ""
    return text or default
