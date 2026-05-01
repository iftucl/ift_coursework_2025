"""Step 1: Stock selection with buffer zone logic.

Selects stocks into long/short baskets based on within-sector percentile
ranking of composite scores. Implements a 3-month buffer zone to reduce
turnover when stocks drift slightly outside the entry threshold.

Buffer rules:
  - Entry: top 10% -> long_core, bottom 10% -> short_core
  - Buffer: 10-20% zone, held for up to 3 months if previously selected
  - Hard stop: beyond 20% -> immediate exit
  - Recovery: return to top/bottom 10% resets buffer to 0
"""

import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd

from modules.db.db_connection import PostgresConnection

logger = logging.getLogger(__name__)
SCHEMA = "team_wittgenstein"

# Valid statuses written to selection_status table
LONG_CORE = "long_core"
LONG_BUFFER = "long_buffer"
SHORT_CORE = "short_core"
SHORT_BUFFER = "short_buffer"
NOT_SELECTED = "not_selected"


@dataclass(frozen=True)
class SelectionConfig:
    """Parameters for stock selection and buffer rules."""

    selection_threshold: float = 0.10
    buffer_exit_threshold: float = 0.20
    buffer_max_months: int = 3


def fetch_composite_scores(
    db: PostgresConnection, rebalance_date: date
) -> pd.DataFrame:
    """Fetch the most recent composite scores before the rebalance date."""
    query = """
        SELECT symbol, score_date, composite_score
        FROM team_wittgenstein.factor_scores
        WHERE score_date = (
            SELECT MAX(score_date)
            FROM team_wittgenstein.factor_scores
            WHERE score_date < :rebalance_date
              AND composite_score IS NOT NULL
        )
        AND composite_score IS NOT NULL
    """
    return db.read_query(query, {"rebalance_date": rebalance_date})


def fetch_previous_selection(
    db: PostgresConnection, rebalance_date: date
) -> pd.DataFrame:
    """Fetch the most recent selection_status before this rebalance date."""
    query = """
        SELECT symbol, status, buffer_months_count, entry_date
        FROM team_wittgenstein.selection_status
        WHERE rebalance_date = (
            SELECT MAX(rebalance_date)
            FROM team_wittgenstein.selection_status
            WHERE rebalance_date < :rebalance_date
        )
    """
    result = db.read_query(query, {"rebalance_date": rebalance_date})
    if result.empty:
        return pd.DataFrame(
            columns=["symbol", "status", "buffer_months_count", "entry_date"]
        )
    return result


def compute_percentile_ranks(scores: pd.DataFrame, sector_map: dict) -> pd.DataFrame:
    """Compute within-sector percentile rank (0=worst, 1=best).

    Stocks without a sector mapping are dropped.
    """
    df = scores.copy()
    df["sector"] = df["symbol"].map(sector_map)
    missing = df["sector"].isna().sum()
    if missing > 0:
        logger.warning("%d stocks have no sector mapping and will be excluded", missing)
        df = df.dropna(subset=["sector"])

    df["percentile_rank"] = df.groupby("sector")["composite_score"].rank(
        pct=True, method="average"
    )
    return df


def apply_selection_rules(
    ranked: pd.DataFrame,
    previous: pd.DataFrame,
    rebalance_date: date,
    config: SelectionConfig,
) -> pd.DataFrame:
    """Apply entry/exit/buffer rules to produce selection status for each stock.

    Returns a DataFrame ready for insertion into selection_status table.
    """
    top = 1.0 - config.selection_threshold  # e.g. 0.90
    top_buffer = 1.0 - config.buffer_exit_threshold  # e.g. 0.80
    bottom = config.selection_threshold  # e.g. 0.10
    bottom_buffer = config.buffer_exit_threshold  # e.g. 0.20

    # Build lookup from previous selection
    prev_lookup = {}
    if not previous.empty:
        for _, row in previous.iterrows():
            prev_lookup[row["symbol"]] = {
                "status": row["status"],
                "buffer_months": row["buffer_months_count"],
                "entry_date": row["entry_date"],
            }

    results = []
    for _, row in ranked.iterrows():
        symbol = row["symbol"]
        rank = row["percentile_rank"]
        sector = row["sector"]
        composite = row["composite_score"]

        prev = prev_lookup.get(symbol, {})
        prev_status = prev.get("status", NOT_SELECTED)
        prev_buffer = prev.get("buffer_months", 0)
        prev_entry = prev.get("entry_date")

        status = NOT_SELECTED
        buffer_months = 0
        entry_date = None
        exit_reason = None

        # --- Long side ---
        if rank >= top:
            # Top 10%: enter or stay as long_core
            status = LONG_CORE
            buffer_months = 0
            entry_date = (
                prev_entry
                if prev_status in (LONG_CORE, LONG_BUFFER)
                else rebalance_date
            )

        elif top_buffer <= rank < top:
            # 80-90th percentile: buffer zone for existing longs
            if prev_status in (LONG_CORE, LONG_BUFFER):
                new_buffer = prev_buffer + 1
                if new_buffer >= config.buffer_max_months:
                    status = NOT_SELECTED
                    exit_reason = "timer_exit"
                else:
                    status = LONG_BUFFER
                    buffer_months = new_buffer
                    entry_date = prev_entry

        # --- Short side ---
        elif rank <= bottom:
            # Bottom 10%: enter or stay as short_core
            status = SHORT_CORE
            buffer_months = 0
            entry_date = (
                prev_entry
                if prev_status in (SHORT_CORE, SHORT_BUFFER)
                else rebalance_date
            )

        elif bottom < rank <= bottom_buffer:
            # 10-20th percentile: buffer zone for existing shorts
            if prev_status in (SHORT_CORE, SHORT_BUFFER):
                new_buffer = prev_buffer + 1
                if new_buffer >= config.buffer_max_months:
                    status = NOT_SELECTED
                    exit_reason = "timer_exit"
                else:
                    status = SHORT_BUFFER
                    buffer_months = new_buffer
                    entry_date = prev_entry

        # --- Hard stop: was selected but now outside buffer zone ---
        if status == NOT_SELECTED and exit_reason is None:
            if prev_status in (LONG_CORE, LONG_BUFFER):
                exit_reason = "hard_stop"
            elif prev_status in (SHORT_CORE, SHORT_BUFFER):
                exit_reason = "hard_stop"

        results.append(
            {
                "symbol": symbol,
                "rebalance_date": rebalance_date,
                "sector": sector,
                "composite_score": composite,
                "percentile_rank": rank,
                "status": status,
                "buffer_months_count": buffer_months,
                "entry_date": entry_date,
                "exit_reason": exit_reason,
            }
        )

    return pd.DataFrame(results)


def persist_selection_status(db: PostgresConnection, selection: pd.DataFrame) -> None:
    """Write selection status to the selection_status table."""
    if selection.empty:
        return

    output = selection[
        [
            "symbol",
            "rebalance_date",
            "sector",
            "composite_score",
            "percentile_rank",
            "status",
            "buffer_months_count",
            "entry_date",
            "exit_reason",
        ]
    ]
    db.write_dataframe_on_conflict_do_nothing(
        output,
        "selection_status",
        SCHEMA,
        conflict_columns=["symbol", "rebalance_date"],
    )
    logger.info(
        "Persisted selection status: %d stocks for %s",
        len(output),
        selection["rebalance_date"].iloc[0],
    )


def run_stock_selection(
    db: PostgresConnection,
    rebalance_date: date,
    sector_map: dict,
    config: SelectionConfig,
    composite_scores: pd.DataFrame | None = None,
    prior_selection: pd.DataFrame | None = None,
    persist: bool = True,
) -> pd.DataFrame:
    """Run full stock selection with buffer rules.

    Args:
        db:               PostgresConnection used for default composite/previous
                          fetches when overrides aren't provided.
        rebalance_date:   Month-end date.
        sector_map:       symbol -> GICS sector mapping.
        config:           SelectionConfig.
        composite_scores: If provided, use this DataFrame (columns: symbol,
                          composite_score) instead of fetching from DB. Used
                          by variant scenarios that compute composites in-memory.
        prior_selection:  If provided, use this DataFrame as the previous
                          month's selection_status (columns: symbol, status,
                          buffer_months_count, entry_date) instead of fetching
                          from DB. Required for variant scenarios that need
                          their own buffer history.
        persist:          When True (default), writes the full selection to
                          selection_status. When False, skips DB writes - used
                          by variant scenarios.

    Returns:
        DataFrame of selected stocks (long_core, long_buffer, short_core,
        short_buffer) with composite scores, sectors, and buffer state.
    """
    # Fetch inputs (use overrides when provided)
    scores = (
        composite_scores
        if composite_scores is not None
        else fetch_composite_scores(db, rebalance_date)
    )
    if scores.empty:
        logger.warning("No composite scores for %s", rebalance_date)
        return pd.DataFrame(
            columns=[
                "symbol",
                "sector",
                "direction",
                "composite_score",
                "percentile_rank",
                "status",
                "buffer_months_count",
            ]
        )

    previous = (
        prior_selection
        if prior_selection is not None
        else fetch_previous_selection(db, rebalance_date)
    )

    # Rank within sectors
    ranked = compute_percentile_ranks(scores, sector_map)

    # Apply buffer rules
    selection = apply_selection_rules(ranked, previous, rebalance_date, config)

    # Persist full selection (including not_selected for audit), gated by flag
    if persist:
        persist_selection_status(db, selection)

    # Filter to selected stocks only
    selected = selection[
        selection["status"].isin([LONG_CORE, LONG_BUFFER, SHORT_CORE, SHORT_BUFFER])
    ].copy()

    # Add direction column for downstream use
    selected["direction"] = selected["status"].apply(
        lambda s: "long" if s in (LONG_CORE, LONG_BUFFER) else "short"
    )

    n_long = (selected["direction"] == "long").sum()
    n_short = (selected["direction"] == "short").sum()
    logger.info(
        "Selected %d stocks (%d long, %d short) for %s",
        len(selected),
        n_long,
        n_short,
        rebalance_date,
    )

    return selected
