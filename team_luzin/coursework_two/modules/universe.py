from __future__ import annotations

import pandas as pd

from modules.models import CW1Inputs


def define_investable_universe(cw1_inputs: CW1Inputs, config: dict) -> pd.DataFrame:
    """
    Define the CW2 investable universe from the latest frozen CW1 outputs only.

    This is a deliberate coursework assumption: CW2 uses the current/latest CW1
    selected universe and evaluates that portfolio over available historical prices.
    It does not perform strict historical monthly re-selection.
    """
    base = cw1_inputs.selections.copy()
    if base.empty:
        base = cw1_inputs.factors.copy()

    df = base.copy()

    if df.empty:
        return df

    min_rows = config["universe"].get("min_rows_per_symbol", 0)
    allowed_sectors = config["universe"].get("allowed_sectors", [])
    required_columns = config["universe"].get("require_columns", [])

    if not cw1_inputs.factors.empty:
        factor_columns = [
            column
            for column in cw1_inputs.factors.columns
            if column == "symbol" or column not in df.columns
        ]
        df = df.merge(cw1_inputs.factors[factor_columns], on="symbol", how="left")

    if required_columns:
        df = df.dropna(subset=[column for column in required_columns if column in df.columns])

    if "symbol" in df.columns and not cw1_inputs.price_history.empty:
        history_counts = (
            cw1_inputs.price_history.groupby("symbol").size().rename("history_rows").reset_index()
        )
        df = df.merge(history_counts, on="symbol", how="left")
        df = df[df["history_rows"].fillna(0) >= min_rows]

    if allowed_sectors and "sector" in df.columns:
        df = df[df["sector"].isin(allowed_sectors)]

    return df.reset_index(drop=True)
