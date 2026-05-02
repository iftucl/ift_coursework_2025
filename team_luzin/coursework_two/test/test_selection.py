import pandas as pd

from modules.selection import select_stocks


def test_select_stocks_applies_sector_cap():
    universe = pd.DataFrame(
        {
            "symbol": [f"T{i}" for i in range(12)] + [f"H{i}" for i in range(5)],
            "sector": ["Tech"] * 12 + ["Health"] * 5,
            "composite_score": list(range(17, 0, -1)),
        }
    )
    config = {"selection": {"min_composite_score": 0.0, "top_n": 12, "sector_cap_names": 9}}

    selected = select_stocks(universe, config)

    assert len(selected) == 12
    assert (selected["sector"] == "Tech").sum() == 9
    assert (selected["sector"] == "Health").sum() == 3
