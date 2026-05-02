import pandas as pd

from modules.robustness import run_robustness_checks


def test_run_robustness_checks_expands_across_configured_scenarios():
    selections = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB"],
            "selection_rank": [1, 2],
            "atr_14": [2.0, 4.0],
            "weight": [0.5, 0.5],
        }
    )
    price_history = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "AAA", "BBB", "BBB", "BBB"],
            "date": pd.to_datetime(
                ["2025-01-31", "2025-02-28", "2025-03-31", "2025-01-31", "2025-02-28", "2025-03-31"]
            ),
            "close": [100, 102, 104, 100, 101, 103],
        }
    )
    config = {
        "project": {"rebalance_frequency": "monthly"},
        "portfolio": {"baseline_weighting": "equal_weight", "max_names": 30},
        "robustness": {
            "enabled": True,
            "weighting_methods": ["equal_weight", "rank_weighted"],
            "rebalance_frequencies": ["monthly", "quarterly"],
            "transaction_cost_bps_values": [10, 20],
        },
        "costs": {"transaction_cost_bps": 10},
    }

    results = run_robustness_checks(selections, price_history, config)

    assert len(results) == 8
    assert {"weighting_method", "rebalance_frequency", "transaction_cost_bps"}.issubset(results.columns)
