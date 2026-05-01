from __future__ import annotations

import pandas as pd

from modules.models import BacktestResults
from modules.portfolio import build_portfolio
from modules.selection import select_stocks


def _normalise_rebalance_frequency(rebalance_frequency: str | None) -> str:
    frequency = (rebalance_frequency or "monthly").strip().lower()
    if frequency not in {"monthly", "quarterly"}:
        raise ValueError(f"Unsupported rebalance frequency: {rebalance_frequency}")
    return frequency


def _get_period_rule(rebalance_frequency: str | None) -> str:
    frequency = _normalise_rebalance_frequency(rebalance_frequency)
    return {"monthly": "ME", "quarterly": "QE"}[frequency]


def _prepare_price_panel(price_history: pd.DataFrame, rebalance_frequency: str | None = None) -> pd.DataFrame:
    if price_history.empty or "date" not in price_history.columns or "close" not in price_history.columns:
        return pd.DataFrame()

    prices = price_history.copy()
    prices["date"] = pd.to_datetime(prices["date"])
    period_rule = _get_period_rule(rebalance_frequency)
    period_prices = (
        prices.sort_values(["symbol", "date"])
        .groupby(["symbol", pd.Grouper(key="date", freq=period_rule)])["close"]
        .last()
        .reset_index()
    )
    return period_prices


def _calculate_turnover(current_holdings: pd.DataFrame, previous_weights: pd.Series) -> float:
    weights = current_holdings.set_index("symbol")["weight"]
    aligned = pd.concat([weights.rename("current"), previous_weights.rename("previous")], axis=1).fillna(0)
    return float((aligned["current"] - aligned["previous"]).abs().sum())


def _find_snapshot_date_column(df: pd.DataFrame) -> str | None:
    for column in ["snapshot_date", "as_of_date", "formation_date", "rebalance_date", "month_end", "date"]:
        if column in df.columns:
            return column
    return None


def _has_historical_snapshots(df: pd.DataFrame) -> bool:
    date_column = _find_snapshot_date_column(df)
    if df.empty or date_column is None:
        return False
    snapshot_dates = pd.to_datetime(df[date_column], errors="coerce").dropna().dt.normalize().nunique()
    return snapshot_dates > 1


def _prepare_snapshot_source(df: pd.DataFrame) -> tuple[pd.DataFrame | None, str | None]:
    date_column = _find_snapshot_date_column(df)
    if df.empty or date_column is None:
        return None, None

    history = df.copy()
    history[date_column] = pd.to_datetime(history[date_column], errors="coerce").dt.normalize()
    sort_columns = [date_column]
    if "symbol" in history.columns:
        sort_columns.append("symbol")
    history = history.dropna(subset=[date_column]).sort_values(sort_columns)
    if history.empty:
        return None, None
    return history, date_column


def _build_point_in_time_universe(
    snapshot: pd.DataFrame,
    price_history: pd.DataFrame,
    config: dict,
    as_of_date: pd.Timestamp,
) -> pd.DataFrame:
    if snapshot.empty:
        return snapshot.copy()

    df = snapshot.copy()
    min_rows = config["universe"].get("min_rows_per_symbol", 0)
    allowed_sectors = config["universe"].get("allowed_sectors", [])
    required_columns = config["universe"].get("require_columns", [])

    if required_columns:
        df = df.dropna(subset=[column for column in required_columns if column in df.columns])

    if "symbol" in df.columns and not price_history.empty:
        history_counts = (
            price_history.loc[pd.to_datetime(price_history["date"]) <= as_of_date]
            .groupby("symbol")
            .size()
            .rename("history_rows")
            .reset_index()
        )
        df = df.merge(history_counts, on="symbol", how="left")
        df = df[df["history_rows"].fillna(0) >= min_rows]

    if allowed_sectors and "sector" in df.columns:
        df = df[df["sector"].isin(allowed_sectors)]

    return df.reset_index(drop=True)


def _build_holdings_for_date(
    snapshot_history: pd.DataFrame,
    date_column: str,
    price_history: pd.DataFrame,
    config: dict,
    formation_date: pd.Timestamp,
    weighting_method: str | None = None,
) -> pd.DataFrame:
    eligible_dates = snapshot_history.loc[snapshot_history[date_column] <= formation_date, date_column]
    if eligible_dates.empty:
        return pd.DataFrame()

    snapshot_date = eligible_dates.max()
    snapshot = snapshot_history[snapshot_history[date_column] == snapshot_date].copy()
    universe = _build_point_in_time_universe(snapshot, price_history, config, formation_date)
    selections = select_stocks(universe, config)
    holdings = build_portfolio(selections, config, weighting_method=weighting_method)
    if holdings.empty:
        return holdings
    holdings["rebalance_date"] = formation_date
    holdings["signal_date"] = snapshot_date
    return holdings


def _calculate_weighted_return(date_slice: pd.DataFrame, holdings: pd.DataFrame) -> float:
    if date_slice.empty or holdings.empty:
        return 0.0
    merged = date_slice.merge(holdings[["symbol", "weight"]], on="symbol", how="inner")
    if merged.empty:
        return 0.0
    return float((merged["asset_return"].fillna(0) * merged["weight"]).sum())


def run_backtest(
    portfolio: pd.DataFrame,
    price_history: pd.DataFrame,
    config: dict,
    rebalance_frequency: str | None = None,
) -> BacktestResults:
    """
    Evaluate the current/latest CW2 portfolio over available historical prices.

    CW2 uses CW1 versioned outputs as fixed inputs. Since these outputs are not
    validated point-in-time rebalance snapshots, this function should be interpreted
    as a constrained historical evaluation of the latest selected portfolio rather
    than a full rolling backtest.
    """
    if portfolio.empty:
        empty = pd.DataFrame()
        return BacktestResults(holdings=empty, returns=empty, equity_curve=empty)

    frequency = _normalise_rebalance_frequency(
        rebalance_frequency or config.get("project", {}).get("rebalance_frequency", "monthly")
    )
    period_prices = _prepare_price_panel(price_history, rebalance_frequency=frequency)
    if period_prices.empty:
        empty = pd.DataFrame()
        return BacktestResults(holdings=portfolio.copy(), returns=empty, equity_curve=empty)

    holdings = portfolio[["symbol", "weight"]].copy()
    tracked = period_prices[period_prices["symbol"].isin(holdings["symbol"])].copy()
    tracked = tracked.sort_values(["symbol", "date"])
    tracked["asset_return"] = tracked.groupby("symbol")["close"].pct_change()

    rebalance_dates = sorted(tracked["date"].dropna().unique())
    previous_weights = pd.Series(dtype=float)
    cost_rate = config.get("costs", {}).get("transaction_cost_bps", 0) / 10000
    rows = []

    for rebalance_date in rebalance_dates:
        date_slice = tracked[tracked["date"] == rebalance_date].merge(holdings, on="symbol", how="inner")
        gross_return = float((date_slice["asset_return"] * date_slice["weight"]).sum())
        turnover = _calculate_turnover(holdings, previous_weights) if len(date_slice) else 0.0
        transaction_cost = turnover * cost_rate
        net_return = gross_return - transaction_cost

        rows.append(
            {
                "date": rebalance_date,
                "gross_return": gross_return,
                "turnover": turnover,
                "transaction_cost": transaction_cost,
                "strategy_return": net_return,
            }
        )
        previous_weights = holdings.set_index("symbol")["weight"]

    strategy_returns = pd.DataFrame(rows)
    strategy_returns["equity_curve"] = (1 + strategy_returns["strategy_return"].fillna(0)).cumprod()

    return BacktestResults(
        holdings=holdings,
        returns=strategy_returns,
        equity_curve=strategy_returns[["date", "equity_curve"]].copy(),
        holdings_history=holdings.assign(rebalance_date=pd.NaT),
        backtest_mode="fixed_latest",
    )


def run_monthly_backtest(portfolio: pd.DataFrame, price_history: pd.DataFrame, config: dict) -> BacktestResults:
    configured_frequency = (
        config.get("backtest", {}).get("rebalance_freq")
        or config.get("project", {}).get("rebalance_frequency")
        or "monthly"
    )
    return run_backtest(portfolio, price_history, config, rebalance_frequency=configured_frequency)


def run_strategy_backtest(
    cw1_inputs,
    portfolio: pd.DataFrame,
    config: dict,
    rebalance_frequency: str | None = None,
    weighting_method: str | None = None,
) -> BacktestResults:
    frequency = _normalise_rebalance_frequency(
        rebalance_frequency or config.get("project", {}).get("rebalance_frequency", "monthly")
    )
    snapshot_candidates = [
        getattr(cw1_inputs, "historical_factors", pd.DataFrame()),
        getattr(cw1_inputs, "historical_selections", pd.DataFrame()),
    ]
    snapshot_source = next((candidate for candidate in snapshot_candidates if _has_historical_snapshots(candidate)), pd.DataFrame())
    prepared_history, date_column = _prepare_snapshot_source(snapshot_source)

    if prepared_history is None or date_column is None:
        return run_backtest(portfolio, cw1_inputs.price_history, config, rebalance_frequency=frequency)

    period_prices = _prepare_price_panel(cw1_inputs.price_history, rebalance_frequency=frequency)
    if period_prices.empty:
        empty = pd.DataFrame()
        return BacktestResults(
            holdings=portfolio.copy(),
            returns=empty,
            equity_curve=empty,
            holdings_history=empty,
            backtest_mode="rolling_point_in_time",
        )

    tracked = period_prices.sort_values(["symbol", "date"]).copy()
    tracked["asset_return"] = tracked.groupby("symbol")["close"].pct_change()
    return_lookup = {date: frame[["symbol", "asset_return"]].copy() for date, frame in tracked.groupby("date")}
    rebalance_dates = sorted(return_lookup.keys())
    if not rebalance_dates:
        empty = pd.DataFrame()
        return BacktestResults(
            holdings=portfolio.copy(),
            returns=empty,
            equity_curve=empty,
            holdings_history=empty,
            backtest_mode="rolling_point_in_time",
        )

    previous_weights = pd.Series(dtype=float)
    active_holdings = pd.DataFrame()
    latest_holdings = portfolio.copy()
    cost_rate = config.get("costs", {}).get("transaction_cost_bps", 0) / 10000
    rows = []
    holdings_records = []

    for rebalance_date in rebalance_dates:
        new_holdings = _build_holdings_for_date(
            prepared_history,
            date_column,
            cw1_inputs.price_history,
            config,
            rebalance_date,
            weighting_method=weighting_method,
        )
        if new_holdings.empty:
            new_holdings = active_holdings.copy()
        if active_holdings.empty and new_holdings.empty:
            rows.append(
                {
                    "date": rebalance_date,
                    "gross_return": 0.0,
                    "turnover": 0.0,
                    "transaction_cost": 0.0,
                    "strategy_return": 0.0,
                }
            )
            continue

        gross_return = _calculate_weighted_return(return_lookup.get(rebalance_date, pd.DataFrame()), active_holdings)
        turnover = _calculate_turnover(new_holdings, previous_weights) if not new_holdings.empty else 0.0
        transaction_cost = turnover * cost_rate
        net_return = gross_return - transaction_cost

        rows.append(
            {
                "date": rebalance_date,
                "gross_return": gross_return,
                "turnover": turnover,
                "transaction_cost": transaction_cost,
                "strategy_return": net_return,
            }
        )

        if not new_holdings.empty:
            holdings_records.append(new_holdings.copy())
            active_holdings = new_holdings.copy()
            previous_weights = active_holdings.set_index("symbol")["weight"]
            latest_holdings = active_holdings.copy()

    strategy_returns = pd.DataFrame(rows)
    strategy_returns["equity_curve"] = (1 + strategy_returns["strategy_return"].fillna(0)).cumprod()
    holdings_history = pd.concat(holdings_records, ignore_index=True) if holdings_records else pd.DataFrame()

    return BacktestResults(
        holdings=latest_holdings,
        returns=strategy_returns,
        equity_curve=strategy_returns[["date", "equity_curve"]].copy(),
        holdings_history=holdings_history,
        backtest_mode="rolling_point_in_time",
    )
