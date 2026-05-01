from __future__ import annotations

import copy

import pandas as pd

from modules.backtest import run_strategy_backtest
from modules.metrics import evaluate_strategy
from modules.models import CW1Inputs
from modules.portfolio import build_portfolio


def _coerce_cw1_inputs(cw1_inputs_or_selections, selections_or_price_history) -> tuple[CW1Inputs, pd.DataFrame]:
    if hasattr(cw1_inputs_or_selections, "price_history"):
        return cw1_inputs_or_selections, selections_or_price_history

    selections = cw1_inputs_or_selections
    price_history = selections_or_price_history
    cw1_inputs = CW1Inputs(
        universe_snapshot=pd.DataFrame(),
        factors=pd.DataFrame(),
        selections=selections.copy(),
        signals=pd.DataFrame(),
        price_history=price_history.copy(),
    )
    return cw1_inputs, selections


def run_robustness_checks(cw1_inputs, selections: pd.DataFrame, config: dict) -> pd.DataFrame:
    if not config["robustness"].get("enabled", True):
        return pd.DataFrame()

    cw1_inputs, selections = _coerce_cw1_inputs(cw1_inputs, selections)

    methods = config["robustness"].get("weighting_methods", ["equal_weight"])
    frequencies = config["robustness"].get(
        "rebalance_frequencies",
        [config.get("project", {}).get("rebalance_frequency", "monthly")],
    )
    transaction_cost_bps_values = config["robustness"].get(
        "transaction_cost_bps_values",
        [config.get("costs", {}).get("transaction_cost_bps", 10)],
    )
    baseline_method = config.get("portfolio", {}).get("baseline_weighting", "equal_weight")
    baseline_frequency = config.get("project", {}).get("rebalance_frequency", "monthly")
    baseline_cost_bps = config.get("costs", {}).get("transaction_cost_bps", 10)
    rows = []

    for frequency in frequencies:
        for method in methods:
            for transaction_cost_bps in transaction_cost_bps_values:
                scenario_config = copy.deepcopy(config)
                scenario_config.setdefault("costs", {})["transaction_cost_bps"] = transaction_cost_bps

                portfolio = build_portfolio(selections, scenario_config, weighting_method=method)
                backtest_results = run_strategy_backtest(
                    cw1_inputs,
                    portfolio,
                    scenario_config,
                    rebalance_frequency=frequency,
                    weighting_method=method,
                )
                metrics = evaluate_strategy(
                    backtest_results.returns,
                    pd.DataFrame(),
                    scenario_config,
                )

                summary = {
                    "rebalance_frequency": frequency,
                    "weighting_method": method,
                    "transaction_cost_bps": transaction_cost_bps,
                    "is_baseline": (
                        method == baseline_method
                        and frequency == baseline_frequency
                        and transaction_cost_bps == baseline_cost_bps
                    ),
                }
                if not backtest_results.returns.empty:
                    summary["average_turnover"] = float(backtest_results.returns["turnover"].fillna(0).mean())
                    summary["average_transaction_cost"] = float(
                        backtest_results.returns["transaction_cost"].fillna(0).mean()
                    )
                if not metrics.empty:
                    first_row = metrics.iloc[0].to_dict()
                    for key, value in first_row.items():
                        if key != "series":
                            summary[key] = value
                rows.append(summary)

    robustness = pd.DataFrame(rows)
    if robustness.empty:
        return robustness

    return robustness.sort_values(
        ["weighting_method", "rebalance_frequency", "transaction_cost_bps"]
    ).reset_index(drop=True)
