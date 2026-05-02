from __future__ import annotations

from pathlib import Path

import pandas as pd
import yfinance as yf


def _normalise_rebalance_frequency(rebalance_frequency: str | None) -> str:
    frequency = (rebalance_frequency or "monthly").strip().lower()
    if frequency not in {"monthly", "quarterly"}:
        raise ValueError(f"Unsupported rebalance frequency: {rebalance_frequency}")
    return frequency


def _get_period_rule(rebalance_frequency: str | None) -> str:
    frequency = _normalise_rebalance_frequency(rebalance_frequency)
    return {"monthly": "ME", "quarterly": "QE"}[frequency]


def _prepare_period_returns(
    price_history: pd.DataFrame,
    rebalance_frequency: str | None = None,
    symbols: list[str] | None = None,
) -> pd.DataFrame:
    if price_history.empty or "date" not in price_history.columns or "close" not in price_history.columns:
        return pd.DataFrame()

    prices = price_history.copy()
    prices["date"] = pd.to_datetime(prices["date"])
    if symbols is not None:
        prices = prices[prices["symbol"].isin(symbols)]

    period_rule = _get_period_rule(rebalance_frequency)
    period_prices = (
        prices.sort_values(["symbol", "date"])
        .groupby(["symbol", pd.Grouper(key="date", freq=period_rule)])["close"]
        .last()
        .reset_index()
    )
    period_prices["asset_return"] = period_prices.groupby("symbol")["close"].pct_change()
    return period_prices


def _find_snapshot_date_column(df: pd.DataFrame) -> str | None:
    for column in ["snapshot_date", "as_of_date", "formation_date", "rebalance_date", "month_end", "date"]:
        if column in df.columns:
            return column
    return None


def _build_rolling_equal_weight_benchmark(
    period_prices: pd.DataFrame,
    snapshot_history: pd.DataFrame,
    investable_universe: pd.DataFrame,
) -> pd.DataFrame:
    if period_prices.empty:
        return pd.DataFrame(columns=["date", "equal_weight_universe"])

    if snapshot_history.empty or "symbol" not in snapshot_history.columns:
        symbols = (
            sorted(investable_universe["symbol"].dropna().unique().tolist())
            if "symbol" in investable_universe.columns
            else []
        )
        if not symbols:
            return pd.DataFrame(columns=["date", "equal_weight_universe"])
        static_prices = period_prices[period_prices["symbol"].isin(symbols)].copy()
        if static_prices.empty:
            return pd.DataFrame(columns=["date", "equal_weight_universe"])
        return (
            static_prices.groupby("date", as_index=False)["asset_return"]
            .mean()
            .rename(columns={"asset_return": "equal_weight_universe"})
        )

    date_column = _find_snapshot_date_column(snapshot_history)
    if date_column is None:
        return pd.DataFrame(columns=["date", "equal_weight_universe"])

    snapshots = snapshot_history.copy()
    snapshots[date_column] = pd.to_datetime(snapshots[date_column], errors="coerce").dt.normalize()
    snapshots = snapshots.dropna(subset=[date_column, "symbol"]).sort_values([date_column, "symbol"])
    if snapshots.empty:
        return pd.DataFrame(columns=["date", "equal_weight_universe"])

    rows = []
    for period_date, date_slice in period_prices.groupby("date"):
        eligible_dates = snapshots.loc[snapshots[date_column] <= pd.Timestamp(period_date).normalize(), date_column]
        if eligible_dates.empty:
            continue
        snapshot_date = eligible_dates.max()
        symbols = snapshots.loc[snapshots[date_column] == snapshot_date, "symbol"].dropna().unique().tolist()
        if not symbols:
            continue
        slice_returns = date_slice.loc[date_slice["symbol"].isin(symbols), "asset_return"].dropna()
        if slice_returns.empty:
            continue
        rows.append({"date": period_date, "equal_weight_universe": float(slice_returns.mean())})

    return pd.DataFrame(rows)


def _load_sp500_series(config: dict, rebalance_frequency: str | None = None) -> pd.DataFrame:
    benchmark_path = Path(config["paths"]["sp500_csv"])
    if not benchmark_path.exists():
        return pd.DataFrame(columns=["date", "sp500"])

    df = pd.read_csv(benchmark_path)
    if "Date" in df.columns:
        df = df.rename(columns={"Date": "date"})
    elif "date" not in df.columns:
        return pd.DataFrame(columns=["date", "sp500"])

    if "Adj Close" in df.columns:
        df["close"] = df["Adj Close"]
    elif "Close" in df.columns:
        df["close"] = df["Close"]
    elif "SP500" in df.columns:
        df["close"] = df["SP500"]
    else:
        return pd.DataFrame(columns=["date", "sp500"])

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["date", "close"])
    df = df.sort_values("date")
    period_rule = _get_period_rule(rebalance_frequency)
    period_prices = df.groupby(pd.Grouper(key="date", freq=period_rule))["close"].last().reset_index()
    period_prices["sp500"] = period_prices["close"].pct_change()
    return period_prices[["date", "sp500"]]


def _save_sp500_history(df: pd.DataFrame, benchmark_path: Path) -> None:
    benchmark_path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = df.copy()
    if isinstance(cleaned.columns, pd.MultiIndex):
        cleaned.columns = [column[0] if isinstance(column, tuple) else column for column in cleaned.columns]

    columns = [column for column in ["Date", "Adj Close", "Close"] if column in cleaned.columns]
    cleaned = cleaned.loc[:, columns]
    if "Date" in cleaned.columns:
        cleaned["Date"] = pd.to_datetime(cleaned["Date"], errors="coerce")
    for column in ["Adj Close", "Close"]:
        if column in cleaned.columns:
            cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")
    cleaned = cleaned.dropna(subset=["Date"])
    cleaned.to_csv(benchmark_path, index=False)


def _clean_local_sp500_file(benchmark_path: Path) -> bool:
    if not benchmark_path.exists():
        return False

    df = pd.read_csv(benchmark_path)
    if "Date" not in df.columns:
        return False

    cleaned = df.copy()
    cleaned["Date"] = pd.to_datetime(cleaned["Date"], errors="coerce")
    for column in ["Adj Close", "Close"]:
        if column in cleaned.columns:
            cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")
    cleaned = cleaned.dropna(subset=["Date"])
    if cleaned.empty:
        return False

    cleaned.to_csv(benchmark_path, index=False)
    return True


def ensure_sp500_data(config: dict) -> dict:
    """
    Ensure a local S&P 500 benchmark file exists for CW2.

    Preference order:
    1. Use existing local file
    2. Download ^GSPC
    3. Fall back to SPY
    """
    benchmark_path = Path(config["paths"]["sp500_csv"])
    status = {
        "benchmark": "sp500",
        "available": False,
        "source": None,
        "ticker_used": None,
        "local_path": str(benchmark_path),
        "message": "",
    }

    if benchmark_path.exists():
        df = pd.read_csv(benchmark_path)
        if "Date" in df.columns and ("Adj Close" in df.columns or "Close" in df.columns):
            _clean_local_sp500_file(benchmark_path)
            status.update(
                {
                    "available": True,
                    "source": "local_file",
                    "ticker_used": "local_file",
                    "message": "Used existing local S&P 500 benchmark file.",
                }
            )
            return status

    for ticker in config.get("benchmark", {}).get("download_tickers", ["^GSPC", "SPY"]):
        try:
            history = yf.download(ticker, period="max", auto_adjust=False, progress=False, threads=False)
        except Exception as exc:
            status["message"] = f"Benchmark download failed for {ticker}: {exc}"
            continue

        if history is None or history.empty:
            status["message"] = f"Benchmark download returned no data for {ticker}."
            continue

        benchmark_df = history.reset_index()
        if "Date" not in benchmark_df.columns:
            date_column = benchmark_df.columns[0]
            benchmark_df = benchmark_df.rename(columns={date_column: "Date"})

        _save_sp500_history(benchmark_df, benchmark_path)
        status.update(
            {
                "available": True,
                "source": "yfinance_download",
                "ticker_used": ticker,
                "message": f"Downloaded benchmark data from yfinance using {ticker}.",
            }
        )
        return status

    status["message"] = "No local benchmark file was available and yfinance download failed."
    return status


def build_benchmark_panel(
    price_history: pd.DataFrame,
    investable_universe: pd.DataFrame,
    config: dict,
    rebalance_frequency: str | None = None,
    snapshot_history: pd.DataFrame | None = None,
) -> pd.DataFrame:
    methods = config.get("benchmark", {}).get("methods", ["equal_weight_universe"])
    frequency = rebalance_frequency or config.get("project", {}).get("rebalance_frequency", "monthly")

    if price_history.empty or "date" not in price_history.columns or "close" not in price_history.columns:
        return pd.DataFrame()

    frames = []

    if "equal_weight_universe" in methods:
        symbols = sorted(investable_universe["symbol"].dropna().unique().tolist()) if "symbol" in investable_universe.columns else None
        period_prices = _prepare_period_returns(price_history, rebalance_frequency=frequency, symbols=symbols)
        benchmark = _build_rolling_equal_weight_benchmark(
            period_prices,
            snapshot_history if snapshot_history is not None else pd.DataFrame(),
            investable_universe,
        )
        frames.append(benchmark)

    if "sp500" in methods:
        config.setdefault("_runtime", {})
        config["_runtime"]["sp500_status"] = ensure_sp500_data(config)
        frames.append(_load_sp500_series(config, rebalance_frequency=frequency))

    if not frames:
        return pd.DataFrame()

    benchmark_panel = frames[0]
    for frame in frames[1:]:
        benchmark_panel = benchmark_panel.merge(frame, on="date", how="outer")

    return benchmark_panel.sort_values("date").reset_index(drop=True)
