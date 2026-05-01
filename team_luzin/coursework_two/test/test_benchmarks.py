import pandas as pd

from modules.benchmarks import build_benchmark_panel


def test_build_benchmark_panel_supports_quarterly_frequency():
    price_history = pd.DataFrame(
        {
            "symbol": ["AAA"] * 6,
            "date": pd.to_datetime(
                ["2025-01-31", "2025-02-28", "2025-03-31", "2025-04-30", "2025-05-31", "2025-06-30"]
            ),
            "close": [100, 102, 105, 108, 110, 115],
        }
    )
    investable_universe = pd.DataFrame({"symbol": ["AAA"]})
    config = {"benchmark": {"methods": ["equal_weight_universe"]}, "project": {"rebalance_frequency": "monthly"}}

    benchmark_panel = build_benchmark_panel(
        price_history,
        investable_universe,
        config,
        rebalance_frequency="quarterly",
    )

    assert benchmark_panel["date"].dt.month.tolist() == [3, 6]
    assert len(benchmark_panel) == 2
