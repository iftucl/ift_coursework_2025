from __future__ import annotations

"""Formal risk-action contract used by intraperiod risk overlays."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class PendingRiskAction:
    """A scheduled risk action to be executed on a future trading day."""

    event_type: str
    action_scope: str
    action_family: str
    urgency: str
    reason_code: str
    scheduled_for: date
    symbol: str = ""
    target_variant: Optional[str] = None
    trim_fraction: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def build_action_event(
    action: PendingRiskAction,
    *,
    event_date: date,
    entry_price: Optional[float] = None,
    open_price: Optional[float] = None,
    high_price: Optional[float] = None,
    low_price: Optional[float] = None,
    execution_price: Optional[float] = None,
    stop_loss_threshold: Optional[float] = None,
    weight_before: Optional[float] = None,
    weight_after: Optional[float] = None,
    regime_before: Optional[str] = None,
    regime_after: Optional[str] = None,
    vix_level: Optional[float] = None,
    vix_daily_return: Optional[float] = None,
    rebalance_scheduled_for: Optional[date] = None,
    transaction_cost: float = 0.0,
    expected_turnover: Optional[float] = None,
    expected_cost: Optional[float] = None,
) -> Dict[str, Any]:
    """Convert a risk action into a database-writable intraday event record."""
    return {
        "event_date": event_date,
        "event_type": action.event_type,
        "symbol": str(action.symbol or ""),
        "entry_price": entry_price,
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "execution_price": execution_price,
        "stop_loss_threshold": stop_loss_threshold,
        "weight_before": weight_before,
        "weight_after": weight_after,
        "regime_before": regime_before,
        "regime_after": regime_after,
        "vix_level": vix_level,
        "vix_daily_return": vix_daily_return,
        "rebalance_scheduled_for": rebalance_scheduled_for,
        "transaction_cost": transaction_cost,
        "action_scope": action.action_scope,
        "action_family": action.action_family,
        "urgency": action.urgency,
        "reason_code": action.reason_code,
        "expected_turnover": expected_turnover,
        "expected_cost": (expected_cost if expected_cost is not None else transaction_cost),
    }
