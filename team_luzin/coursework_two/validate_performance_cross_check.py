from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd


TOLERANCE = 1e-8


def compute_metrics(returns: pd.Series) -> dict[str, float]:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    observations = int(clean.shape[0])

    if observations == 0:
        return {
            "observations": 0,
            "cumulative_return": np.nan,
            "annual_return": np.nan,
            "annual_volatility": np.nan,
            "sharpe_ratio": np.nan,
            "sortino_ratio": np.nan,
            "max_drawdown": np.nan,
            "calmar_ratio": np.nan,
            "win_rate": np.nan,
        }

    cumulative_return = float((1 + clean).prod() - 1)
    annual_return = float((1 + cumulative_return) ** (12 / observations) - 1)

    annual_volatility = float(clean.std() * math.sqrt(12))
    sharpe_ratio = float(annual_return / annual_volatility) if annual_volatility > 0 else np.nan

    downside = clean[clean < 0]
    downside_vol = float(downside.std() * math.sqrt(12)) if not downside.empty else np.nan
    sortino_ratio = float(annual_return / downside_vol) if downside_vol and downside_vol > 0 else np.nan

    equity_curve = (1 + clean).cumprod()
    drawdown = equity_curve / equity_curve.cummax() - 1
    max_drawdown = float(drawdown.min())
    calmar_ratio = float(annual_return / abs(max_drawdown)) if max_drawdown < 0 else np.nan

    win_rate = float((clean > 0).mean())

    return {
        "observations": observations,
        "cumulative_return": cumulative_return,
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "max_drawdown": max_drawdown,
        "calmar_ratio": calmar_ratio,
        "win_rate": win_rate,
    }


def compute_drawdown_details(dates: pd.Series, returns: pd.Series) -> dict[str, object]:
    series = pd.to_numeric(returns, errors="coerce")
    frame = pd.DataFrame({"date": pd.to_datetime(dates), "return": series}).dropna().sort_values("date")

    if frame.empty:
        return {
            "peak_date": pd.NaT,
            "trough_date": pd.NaT,
            "peak_equity": np.nan,
            "trough_equity": np.nan,
            "max_drawdown": np.nan,
        }

    frame["equity"] = (1 + frame["return"]).cumprod()
    frame["rolling_peak"] = frame["equity"].cummax()
    frame["drawdown"] = frame["equity"] / frame["rolling_peak"] - 1

    trough_idx = frame["drawdown"].idxmin()
    trough_row = frame.loc[trough_idx]

    history_to_trough = frame.loc[:trough_idx]
    peak_idx = history_to_trough["equity"].idxmax()
    peak_row = frame.loc[peak_idx]

    return {
        "peak_date": peak_row["date"],
        "trough_date": trough_row["date"],
        "peak_equity": float(peak_row["equity"]),
        "trough_equity": float(trough_row["equity"]),
        "max_drawdown": float(trough_row["drawdown"]),
    }


def comparison_rows(
    source_name: str,
    reported: pd.DataFrame,
    metric_rows: dict[str, dict[str, float]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if reported.empty:
        return rows

    reported_map = {
        "observations": "observations",
        "cumulative_return": "cumulative_return",
        "annual_return": "annual_return",
        "annual_volatility": "annual_volatility",
        "sharpe_ratio": "sharpe_ratio",
        "sortino_ratio": "sortino_ratio",
        "max_drawdown": "max_drawdown",
        "calmar_ratio": "calmar_ratio",
        "win_rate": "positive_month_ratio",
    }

    for series_name, calculated in metric_rows.items():
        source_row = reported[reported["series"] == series_name]
        if source_row.empty:
            for metric in reported_map:
                rows.append(
                    {
                        "source": source_name,
                        "series": series_name,
                        "metric": metric,
                        "reported_value": np.nan,
                        "recalculated_value": calculated.get(metric, np.nan),
                        "difference": np.nan,
                        "pass": False,
                    }
                )
            continue

        source_row_dict = source_row.iloc[0].to_dict()
        for metric, source_metric in reported_map.items():
            reported_value = source_row_dict.get(source_metric, np.nan)
            recalculated_value = calculated.get(metric, np.nan)

            if pd.isna(reported_value) or pd.isna(recalculated_value):
                difference = np.nan
                passed = False
            else:
                difference = float(reported_value) - float(recalculated_value)
                passed = abs(difference) <= TOLERANCE

            rows.append(
                {
                    "source": source_name,
                    "series": series_name,
                    "metric": metric,
                    "reported_value": reported_value,
                    "recalculated_value": recalculated_value,
                    "difference": difference,
                    "pass": bool(passed),
                }
            )

    return rows


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    outputs_dir = base_dir / "outputs"

    monthly_returns_path = outputs_dir / "backtest" / "monthly_returns.csv"
    benchmark_returns_path = outputs_dir / "benchmark" / "benchmark_returns.csv"
    performance_table_path = outputs_dir / "performance" / "performance_table.csv"
    absolute_summary_path = outputs_dir / "performance" / "absolute_performance_summary.csv"
    robustness_path = outputs_dir / "robustness" / "weighting_comparison.csv"

    monthly = pd.read_csv(monthly_returns_path)
    benchmark = pd.read_csv(benchmark_returns_path)

    monthly["date"] = pd.to_datetime(monthly["date"], errors="coerce")
    benchmark["date"] = pd.to_datetime(benchmark["date"], errors="coerce")

    strategy = monthly[["date", "strategy_return"]].rename(columns={"strategy_return": "strategy"})
    merged = strategy.merge(benchmark[["date", "equal_weight_universe", "sp500"]], on="date", how="inner")
    aligned = merged.dropna(subset=["strategy", "equal_weight_universe", "sp500"]).sort_values("date").reset_index(drop=True)

    metric_rows: dict[str, dict[str, float]] = {}
    drawdown_rows: list[dict[str, object]] = []

    for series_name, column in [
        ("strategy", "strategy"),
        ("equal_weight_universe", "equal_weight_universe"),
        ("sp500", "sp500"),
    ]:
        metric_rows[series_name] = compute_metrics(aligned[column])
        details = compute_drawdown_details(aligned["date"], aligned[column])
        drawdown_rows.append(
            {
                "series": series_name,
                "peak_date": details["peak_date"],
                "trough_date": details["trough_date"],
                "peak_equity": details["peak_equity"],
                "trough_equity": details["trough_equity"],
                "max_drawdown": details["max_drawdown"],
            }
        )

    performance_table = pd.read_csv(performance_table_path)
    absolute_summary = pd.read_csv(absolute_summary_path) if absolute_summary_path.exists() else pd.DataFrame()

    robustness = pd.read_csv(robustness_path)
    baseline = robustness[robustness["is_baseline"].astype(str).str.lower() == "true"].copy()
    if baseline.empty:
        raise ValueError("No baseline row found in robustness/weighting_comparison.csv")

    baseline = baseline.head(1).copy()
    baseline["series"] = "strategy"

    comparison: list[dict[str, object]] = []
    comparison.extend(comparison_rows("performance_table", performance_table, metric_rows))
    if not absolute_summary.empty:
        comparison.extend(comparison_rows("absolute_performance_summary", absolute_summary, metric_rows))
    comparison.extend(comparison_rows("robustness_baseline", baseline, {"strategy": metric_rows["strategy"]}))

    comparison_df = pd.DataFrame(comparison)
    comparison_df = comparison_df.sort_values(["source", "series", "metric"]).reset_index(drop=True)

    drawdown_df = pd.DataFrame(drawdown_rows)

    validation_dir = outputs_dir / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)

    performance_out = validation_dir / "performance_cross_check.csv"
    drawdown_out = validation_dir / "drawdown_cross_check.csv"

    comparison_df.to_csv(performance_out, index=False)
    drawdown_df.to_csv(drawdown_out, index=False)

    print("Aligned observations (all 3 series with non-null returns):", len(aligned))
    print("\nDrawdown details:")
    print(drawdown_df.to_string(index=False))

    print("\nComparison summary by source:")
    summary = comparison_df.groupby(["source", "pass"]).size().unstack(fill_value=0)
    print(summary.to_string())

    failing = comparison_df[~comparison_df["pass"]]
    passing = comparison_df[comparison_df["pass"]]

    print("\nPassing metrics:")
    if passing.empty:
        print("  None")
    else:
        for _, row in passing.iterrows():
            print(f"  PASS {row['source']} | {row['series']} | {row['metric']}")

    print("\nFailing metrics:")
    if failing.empty:
        print("  None")
    else:
        for _, row in failing.iterrows():
            diff = row["difference"]
            diff_text = "nan" if pd.isna(diff) else f"{diff:.12g}"
            print(f"  FAIL {row['source']} | {row['series']} | {row['metric']} | diff={diff_text}")

    print(f"\nSaved: {performance_out}")
    print(f"Saved: {drawdown_out}")


if __name__ == "__main__":
    main()
