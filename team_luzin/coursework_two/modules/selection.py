from __future__ import annotations

import pandas as pd


def select_stocks(universe: pd.DataFrame, config: dict) -> pd.DataFrame:
    if universe.empty:
        return universe.copy()

    df = universe.copy()

    score_column = "composite_score" if "composite_score" in df.columns else None
    if score_column is None:
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        score_column = numeric_cols[0] if numeric_cols else None

    if score_column is None:
        return df.head(0).copy()

    min_score = config["selection"].get("min_composite_score", 0.0)
    top_n = config["selection"].get("top_n", 30)
    sector_cap_names = config["selection"].get("sector_cap_names", top_n)

    eligible = df[df[score_column] >= min_score].sort_values(score_column, ascending=False)
    selected_rows = []
    sector_counts: dict[str, int] = {}

    for _, row in eligible.iterrows():
        sector = row.get("sector", "Unknown")
        if sector_counts.get(sector, 0) >= sector_cap_names:
            continue
        selected_rows.append(row)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        if len(selected_rows) >= top_n:
            break

    if not selected_rows:
        selected = eligible.head(0).copy()
        selected["selection_score"] = pd.Series(dtype=float)
        selected["selection_rank"] = pd.Series(dtype=int)
        return selected

    selected = pd.DataFrame(selected_rows).reset_index(drop=True)
    selected["selection_score"] = selected[score_column]
    selected["selection_rank"] = range(1, len(selected) + 1)
    return selected
