from __future__ import annotations

import math

import pandas as pd


def _build_return_panel(strategy_returns: pd.DataFrame, benchmarks: pd.DataFrame) -> pd.DataFrame:
    panel = strategy_returns.copy()
    if not benchmarks.empty and "date" in benchmarks.columns:
        panel = panel.merge(benchmarks, on="date", how="left")
    return panel.sort_values("date").reset_index(drop=True) if "date" in panel.columns else panel


def _equity_curve(returns: pd.Series) -> pd.Series:
    clean = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    return (1 + clean).cumprod()


def _downside_deviation(returns: pd.Series) -> float:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        return 0.0

    downside = clean[clean < 0]
    if downside.empty or downside.shape[0] < 2:
        return 0.0

    return float(downside.std(ddof=1) * math.sqrt(12))


def _cumulative_return(returns: pd.Series) -> float:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    return (1 + clean).prod() - 1


def _annualise_return(returns: pd.Series) -> float:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    compounded = (1 + clean).prod()
    periods = len(clean)
    return compounded ** (12 / periods) - 1


def _annualise_volatility(returns: pd.Series) -> float:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty or clean.shape[0] < 2:
        return 0.0
    return float(clean.std(ddof=1) * math.sqrt(12))


def _max_drawdown(returns: pd.Series) -> float:
    clean = pd.to_numeric(returns, errors="coerce").fillna(0)
    if clean.empty:
        return 0.0
    equity = (1 + clean).cumprod()
    drawdown = equity / equity.cummax() - 1
    return float(drawdown.min())


def _summarise_series(name: str, returns: pd.Series) -> dict:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    annual_return = _annualise_return(clean)
    annual_volatility = _annualise_volatility(clean)
    downside_deviation = _downside_deviation(clean)
    max_drawdown = _max_drawdown(clean)
    sharpe_ratio = annual_return / annual_volatility if annual_volatility > 0 else 0.0
    sortino_ratio = annual_return / downside_deviation if downside_deviation > 0 else 0.0
    calmar_ratio = annual_return / abs(max_drawdown) if max_drawdown < 0 else 0.0
    return {
        "series": name,
        "observations": int(clean.shape[0]),
        "cumulative_return": _cumulative_return(clean),
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "calmar_ratio": calmar_ratio,
        "max_drawdown": max_drawdown,
        "downside_deviation": downside_deviation,
        "average_monthly_return": float(clean.mean()) if not clean.empty else 0.0,
        "median_monthly_return": float(clean.median()) if not clean.empty else 0.0,
        "best_month": float(clean.max()) if not clean.empty else 0.0,
        "worst_month": float(clean.min()) if not clean.empty else 0.0,
        "positive_month_ratio": float((clean > 0).mean()) if not clean.empty else 0.0,
    }


def build_return_series_panel(strategy_returns: pd.DataFrame, benchmarks: pd.DataFrame) -> pd.DataFrame:
    panel = _build_return_panel(strategy_returns, benchmarks)
    if panel.empty:
        return pd.DataFrame()

    if "net_return" not in panel.columns and "strategy_return" in panel.columns:
        panel["net_return"] = panel["strategy_return"]

    return_columns = [
        column
        for column in panel.columns
        if column != "date" and (column.endswith("_return") or column in {"equal_weight_universe", "sp500"})
    ]

    for column in return_columns:
        equity = _equity_curve(panel[column])
        panel[f"{column}_cumulative_return"] = equity - 1
        panel[f"{column}_drawdown"] = equity / equity.cummax() - 1

    return panel


def build_rolling_metrics_panel(strategy_returns: pd.DataFrame, window: int = 12) -> pd.DataFrame:
    if strategy_returns.empty or "strategy_return" not in strategy_returns.columns:
        return pd.DataFrame(columns=["date", "rolling_12m_return", "rolling_12m_volatility", "rolling_12m_sharpe"])

    rolling = strategy_returns[["date", "strategy_return"]].copy().sort_values("date").reset_index(drop=True)
    returns = pd.to_numeric(rolling["strategy_return"], errors="coerce")

    rolling["rolling_12m_return"] = (1 + returns).rolling(window=window).apply(lambda x: x.prod() - 1, raw=False)
    rolling["rolling_12m_volatility"] = returns.rolling(window=window).std(ddof=1) * math.sqrt(12)
    rolling["rolling_12m_sharpe"] = (
        rolling["rolling_12m_return"] / rolling["rolling_12m_volatility"]
    ).where(rolling["rolling_12m_volatility"] > 0, 0.0)
    return rolling


def build_sector_exposure_summary(holdings: pd.DataFrame) -> pd.DataFrame:
    if holdings.empty or "weight" not in holdings.columns:
        return pd.DataFrame(columns=["sector", "holdings_count", "sector_weight"])

    sector_column = next((column for column in ["sector", "gics_sector"] if column in holdings.columns), None)
    if sector_column is None:
        return pd.DataFrame(columns=["sector", "holdings_count", "sector_weight"])

    return (
        holdings.groupby(sector_column, dropna=False)
        .agg(holdings_count=("symbol", "nunique"), sector_weight=("weight", "sum"))
        .reset_index()
        .rename(columns={sector_column: "sector"})
        .sort_values(["sector_weight", "sector"], ascending=[False, True])
        .reset_index(drop=True)
    )


def build_portfolio_diagnostics(holdings: pd.DataFrame, strategy_returns: pd.DataFrame) -> pd.DataFrame:
    sector_exposure = build_sector_exposure_summary(holdings)
    max_sector_weight = float(sector_exposure["sector_weight"].max()) if not sector_exposure.empty else 0.0
    average_holdings_count = (
        float(pd.to_numeric(strategy_returns["holdings_count"], errors="coerce").mean())
        if "holdings_count" in strategy_returns.columns and not strategy_returns.empty
        else float(holdings["symbol"].nunique()) if not holdings.empty and "symbol" in holdings.columns
        else 0.0
    )
    average_turnover = (
        float(pd.to_numeric(strategy_returns["turnover"], errors="coerce").mean())
        if "turnover" in strategy_returns.columns and not strategy_returns.empty
        else 0.0
    )

    return pd.DataFrame(
        [
            {"metric": "average_holdings_count", "value": average_holdings_count},
            {"metric": "max_sector_weight", "value": max_sector_weight},
            {"metric": "average_turnover", "value": average_turnover},
        ]
    )


def evaluate_strategy(strategy_returns: pd.DataFrame, benchmarks: pd.DataFrame, config: dict, rebalance_frequency: str | None = None) -> pd.DataFrame:
    del config

    if strategy_returns.empty:
        return pd.DataFrame()

    merged = _build_return_panel(strategy_returns, benchmarks)
    rows = [_summarise_series("strategy", merged["strategy_return"])]

    for column in benchmarks.columns if "date" in benchmarks.columns else []:
        if column == "date" or not merged[column].dropna().any():
            continue
        rows.append(_summarise_series(column, merged[column]))

    return pd.DataFrame(rows)


def build_diversification_summary(portfolio: pd.DataFrame) -> pd.DataFrame:
    if portfolio.empty or "weight" not in portfolio.columns:
        return pd.DataFrame(columns=["metric", "value"])

    weights = pd.to_numeric(portfolio["weight"], errors="coerce").dropna()
    if weights.empty:
        return pd.DataFrame(columns=["metric", "value"])

    weights = weights / weights.sum() if weights.sum() > 0 else weights
    n_holdings = int((weights > 0).sum())
    hhi = float((weights ** 2).sum())
    effective_n = round(1 / hhi, 4) if hhi > 0 else 0.0
    top5_weight = float(weights.nlargest(5).sum())
    top10_weight = float(weights.nlargest(10).sum())

    rows = [
        {"metric": "n_holdings", "value": n_holdings},
        {"metric": "herfindahl_hirschman_index", "value": round(hhi, 6)},
        {"metric": "effective_n", "value": effective_n},
        {"metric": "top5_weight", "value": round(top5_weight, 6)},
        {"metric": "top10_weight", "value": round(top10_weight, 6)},
    ]
    return pd.DataFrame(rows)


def build_sector_weight_breakdown(portfolio: pd.DataFrame) -> pd.DataFrame:
    if portfolio.empty or "weight" not in portfolio.columns:
        return pd.DataFrame(columns=["sector", "total_weight"])

    sector_column = next(
        (col for col in ["sector", "gics_sector"] if col in portfolio.columns), None
    )
    if sector_column is None:
        return pd.DataFrame(columns=["sector", "total_weight"])

    return (
        portfolio.groupby(sector_column, dropna=False)["weight"]
        .sum()
        .reset_index()
        .rename(columns={sector_column: "sector", "weight": "total_weight"})
        .sort_values("total_weight", ascending=False)
        .reset_index(drop=True)
    )


def build_benchmark_comparison_summary(
    strategy_returns: pd.DataFrame,
    benchmarks: pd.DataFrame,
    config: dict,
    rebalance_frequency: str | None = None,
) -> pd.DataFrame:
    if strategy_returns.empty:
        return pd.DataFrame()

    benchmark_methods = config.get("benchmark", {}).get("methods", [])
    merged = _build_return_panel(strategy_returns, benchmarks)
    rows = []

    for benchmark_name in benchmark_methods:
        if benchmark_name not in merged.columns:
            rows.append({"benchmark": benchmark_name, "available": False})
            continue

        aligned = merged[["strategy_return", benchmark_name]].dropna()
        if aligned.empty:
            rows.append({"benchmark": benchmark_name, "available": False})
            continue

        excess = aligned["strategy_return"] - aligned[benchmark_name]
        tracking_error = _annualise_volatility(excess)
        bm_var = float(aligned[benchmark_name].var(ddof=1))
        beta = float(aligned["strategy_return"].cov(aligned[benchmark_name]) / bm_var) if bm_var > 0 else 0.0
        alpha = _annualise_return(aligned["strategy_return"]) - beta * _annualise_return(aligned[benchmark_name])
        rows.append(
            {
                "benchmark": benchmark_name,
                "available": True,
                "strategy_annual_return": _annualise_return(aligned["strategy_return"]),
                "benchmark_annual_return": _annualise_return(aligned[benchmark_name]),
                "excess_annual_return": _annualise_return(excess),
                "tracking_error": tracking_error,
                "information_ratio": (
                    _annualise_return(excess) / tracking_error if tracking_error > 0 else 0.0
                ),
                "correlation": aligned["strategy_return"].corr(aligned[benchmark_name]),
                "beta": beta,
                "alpha": alpha,
            }
        )

    return pd.DataFrame(rows)
