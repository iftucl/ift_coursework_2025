import pandas as pd

from modules.portfolio import build_portfolio


def test_build_portfolio_equal_weight_default():
    selections = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "selection_score": [1.0, 0.8, 0.5],
        }
    )
    config = {"portfolio": {"baseline_weighting": "equal_weight", "max_names": 3}}

    portfolio = build_portfolio(selections, config)

    assert len(portfolio) == 3
    assert round(portfolio["weight"].sum(), 8) == 1.0
    assert portfolio["weighting_method"].iloc[0] == "equal_weight"
