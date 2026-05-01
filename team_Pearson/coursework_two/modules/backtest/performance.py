from __future__ import annotations

"""Portfolio return and NAV helpers for the CW2 backtest engine."""

from typing import Mapping


def compute_gross_return(
    target_weights: Mapping[str, float],
    period_returns: Mapping[str, float],
) -> float:
    """Compute long-only gross portfolio return from target weights and asset returns."""
    gross = 0.0
    for symbol, weight in target_weights.items():
        gross += float(weight) * float(period_returns.get(symbol, 0.0))
    return gross


def compute_net_return(gross_return: float, transaction_cost: float) -> float:
    """Compute exact period net return after execution-time cost deduction."""
    return (1.0 + float(gross_return)) * (1.0 - float(transaction_cost)) - 1.0


def update_nav(nav: float, gross_return: float, transaction_cost: float) -> float:
    """Update strategy NAV using execution-time transaction cost semantics."""
    return float(nav) * (1.0 + float(gross_return)) * (1.0 - float(transaction_cost))


def update_benchmark_nav(nav: float, benchmark_return: float) -> float:
    """Update benchmark NAV without any transaction cost deduction."""
    return float(nav) * (1.0 + float(benchmark_return))
