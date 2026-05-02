from __future__ import annotations

"""Build fixed historical sub-period tables aligned with the coursework requirement sheet."""

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd
from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[3]
CW1_ROOT = REPO_ROOT / "team_Pearson" / "coursework_one"
CW2_ROOT = REPO_ROOT / "team_Pearson" / "coursework_two"

for path in (str(REPO_ROOT), str(CW1_ROOT)):
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)

from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine  # noqa: E402
from team_Pearson.coursework_two.scripts.orchestration import load_env_layers  # noqa: E402

_SCHEMA = "systematic_equity"
_DEFAULT_RUN_ID = "6905e84b-9e16-4106-8c0f-cd9ecce56728"
_DEFAULT_OUTPUT_ROOT = CW2_ROOT / "outputs" / "robustness" / "subperiod"

_SUBPERIOD_WINDOWS = [
    (
        "reopening_2021",
        "2021 Reopening",
        date(2021, 4, 20),
        date(2021, 12, 31),
        "Post-COVID reopening and policy normalization",
    ),
    ("bear_2022", "2022 Bear", date(2022, 1, 1), date(2022, 12, 31), "Rates and growth drawdown"),
    (
        "recovery_2023",
        "2023 Recovery",
        date(2023, 1, 1),
        date(2023, 12, 31),
        "Post-drawdown recovery",
    ),
    ("bull_2024", "2024 Bull", date(2024, 1, 1), date(2024, 12, 31), "AI-led bull market"),
    (
        "recent_2025_2026",
        "2025-2026 Recent",
        date(2025, 1, 1),
        date(2026, 4, 20),
        "Recent formal-run holding periods",
    ),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build fixed sub-period analysis tables for the main CW2 baseline run."
    )
    parser.add_argument("--run-id", default=_DEFAULT_RUN_ID)
    parser.add_argument("--output-root", default=str(_DEFAULT_OUTPUT_ROOT))
    return parser


def _annualized_return(returns: Iterable[float], periods_per_year: int = 12) -> Optional[float]:
    series = pd.Series(list(returns), dtype=float).dropna()
    if series.empty:
        return None
    total = float(np.prod(1.0 + series.to_numpy(dtype=float)))
    if total <= 0.0:
        return -1.0
    return float(total ** (periods_per_year / len(series)) - 1.0)


def _annualized_volatility(returns: Iterable[float], periods_per_year: int = 12) -> Optional[float]:
    series = pd.Series(list(returns), dtype=float).dropna()
    if len(series) < 2:
        return None
    return float(series.std(ddof=1) * math.sqrt(periods_per_year))


def _max_drawdown(returns: Iterable[float]) -> Optional[float]:
    series = pd.Series(list(returns), dtype=float).dropna()
    if series.empty:
        return None
    nav = (1.0 + series).cumprod()
    peaks = nav.cummax()
    return float((nav / peaks - 1.0).min())


def _safe_divide(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator in {None, 0}:
        return None
    if denominator is not None and pd.isna(denominator):
        return None
    return float(numerator) / float(denominator)


def _fetch_strategy_series(run_id: str) -> pd.DataFrame:
    engine = get_db_engine()
    sql = text(f"""
        SELECT period_end_date, net_return, benchmark_return, regime
        FROM {_SCHEMA}.backtest_performance
        WHERE run_id = :run_id
        ORDER BY period_end_date
        """)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"run_id": run_id})
    df["period_end_date"] = pd.to_datetime(df["period_end_date"])
    for col in ("net_return", "benchmark_return"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _fetch_benchmark_series(run_id: str) -> pd.DataFrame:
    engine = get_db_engine()
    sql = text(f"""
        SELECT period_end_date, series_name, period_return
        FROM {_SCHEMA}.backtest_benchmark_nav
        WHERE run_id = :run_id
        ORDER BY period_end_date, series_name
        """)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"run_id": run_id})
    df["period_end_date"] = pd.to_datetime(df["period_end_date"])
    df["period_return"] = pd.to_numeric(df["period_return"], errors="coerce")
    return df


def _compute_window_metrics(
    strategy_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    *,
    window_key: str,
    window_label: str,
    start_date: date,
    end_date: date,
    market_context: str,
) -> List[Dict[str, Any]]:
    available_series = ["SPY"] + sorted(
        str(series_name)
        for series_name in benchmark_df["series_name"].dropna().unique().tolist()
        if str(series_name) != "SPY"
    )
    mask = (strategy_df["period_end_date"] >= pd.Timestamp(start_date)) & (
        strategy_df["period_end_date"] <= pd.Timestamp(end_date)
    )
    strat_window = strategy_df.loc[mask].copy()
    if strat_window.empty:
        return [
            {
                "window_key": window_key,
                "window_label": window_label,
                "market_context": market_context,
                "versus_series": series_name,
                "n_periods": 0,
                "strategy_ann_return": None,
                "strategy_ann_volatility": None,
                "strategy_sharpe": None,
                "strategy_max_drawdown": None,
                "versus_ann_return": None,
                "excess_ann_return": None,
            }
            for series_name in available_series
        ]

    out: List[Dict[str, Any]] = []
    strategy_ann_return = _annualized_return(strat_window["net_return"])
    strategy_ann_vol = _annualized_volatility(strat_window["net_return"])
    strategy_sharpe = _safe_divide(strategy_ann_return, strategy_ann_vol)
    strategy_max_dd = _max_drawdown(strat_window["net_return"])

    for series_name, group in benchmark_df.groupby("series_name"):
        bench_window = group.loc[
            (group["period_end_date"] >= pd.Timestamp(start_date))
            & (group["period_end_date"] <= pd.Timestamp(end_date))
        ].copy()
        if bench_window.empty:
            continue
        joined = strat_window[["period_end_date", "net_return"]].merge(
            bench_window[["period_end_date", "period_return"]],
            on="period_end_date",
            how="inner",
        )
        if joined.empty:
            continue
        ann_return = _annualized_return(joined["period_return"])
        out.append(
            {
                "window_key": window_key,
                "window_label": window_label,
                "market_context": market_context,
                "versus_series": str(series_name),
                "n_periods": int(len(joined)),
                "strategy_ann_return": strategy_ann_return,
                "strategy_ann_volatility": strategy_ann_vol,
                "strategy_sharpe": strategy_sharpe,
                "strategy_max_drawdown": strategy_max_dd,
                "versus_ann_return": ann_return,
                "excess_ann_return": (
                    None
                    if strategy_ann_return is None or ann_return is None
                    else strategy_ann_return - ann_return
                ),
            }
        )
    if benchmark_df[benchmark_df["series_name"] == "SPY"].empty:
        spy_ann_return = _annualized_return(strat_window["benchmark_return"])
        out.append(
            {
                "window_key": window_key,
                "window_label": window_label,
                "market_context": market_context,
                "versus_series": "SPY",
                "n_periods": int(len(strat_window)),
                "strategy_ann_return": strategy_ann_return,
                "strategy_ann_volatility": strategy_ann_vol,
                "strategy_sharpe": strategy_sharpe,
                "strategy_max_drawdown": strategy_max_dd,
                "versus_ann_return": spy_ann_return,
                "excess_ann_return": (
                    None
                    if strategy_ann_return is None or spy_ann_return is None
                    else strategy_ann_return - spy_ann_return
                ),
            }
        )
    return out


def _to_markdown(df: pd.DataFrame) -> str:
    lines = [
        "# Sub-Period Analysis",
        "",
        "| Window | Versus | N Periods | Strategy Ann Return | Sharpe | Max DD | Versus Ann Return | Excess Ann Return |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in df.to_dict(orient="records"):

        def _fmt_pct(value: Any) -> str:
            return "NA" if value is None or pd.isna(value) else f"{float(value) * 100.0:.3f}%"

        def _fmt_num(value: Any) -> str:
            return "NA" if value is None or pd.isna(value) else f"{float(value):.3f}"

        lines.append(
            f"| {row['window_label']} | {row['versus_series']} | {int(row['n_periods'])} | {_fmt_pct(row['strategy_ann_return'])} | {_fmt_num(row['strategy_sharpe'])} | {_fmt_pct(row['strategy_max_drawdown'])} | {_fmt_pct(row['versus_ann_return'])} | {_fmt_pct(row['excess_ann_return'])} |"
        )
    return "\n".join(lines) + "\n"


def _coverage_note(strategy_df: pd.DataFrame) -> Dict[str, Any]:
    available = strategy_df["period_end_date"].dropna().sort_values()
    first_date = None if available.empty else available.iloc[0].date().isoformat()
    last_date = None if available.empty else available.iloc[-1].date().isoformat()
    uncovered_windows = []
    for window_key, window_label, start_date, end_date, market_context in _SUBPERIOD_WINDOWS:
        mask = (strategy_df["period_end_date"] >= pd.Timestamp(start_date)) & (
            strategy_df["period_end_date"] <= pd.Timestamp(end_date)
        )
        n_periods = int(mask.sum())
        if n_periods <= 0:
            uncovered_windows.append(
                {
                    "window_key": window_key,
                    "window_label": window_label,
                    "requested_start": start_date.isoformat(),
                    "requested_end": end_date.isoformat(),
                    "market_context": market_context,
                }
            )
    return {
        "available_start": first_date,
        "available_end": last_date,
        "uncovered_windows": uncovered_windows,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    load_env_layers()

    output_root = Path(str(args.output_root)).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    strategy_df = _fetch_strategy_series(str(args.run_id))
    benchmark_df = _fetch_benchmark_series(str(args.run_id))
    rows: List[Dict[str, Any]] = []
    for window_key, window_label, start_date, end_date, market_context in _SUBPERIOD_WINDOWS:
        rows.extend(
            _compute_window_metrics(
                strategy_df,
                benchmark_df,
                window_key=window_key,
                window_label=window_label,
                start_date=start_date,
                end_date=end_date,
                market_context=market_context,
            )
        )
    df = pd.DataFrame(rows)
    coverage = _coverage_note(strategy_df)
    df.to_csv(output_root / "subperiod_analysis.csv", index=False, encoding="utf-8-sig")
    (output_root / "subperiod_analysis.md").write_text(_to_markdown(df), encoding="utf-8")
    (output_root / "subperiod_analysis.json").write_text(
        json.dumps(df.to_dict(orient="records"), indent=2, default=str),
        encoding="utf-8",
    )
    coverage_lines = [
        "# Sub-Period Coverage Note",
        "",
        f"- Available realized series start: `{coverage['available_start']}`",
        f"- Available realized series end: `{coverage['available_end']}`",
    ]
    if coverage["uncovered_windows"]:
        coverage_lines.extend(
            [
                "",
                "The following fixed windows have no baseline observations in the current code-aligned run and therefore remain unavailable rather than estimated from external proxy data:",
                "",
            ]
        )
        for item in coverage["uncovered_windows"]:
            coverage_lines.append(
                f"- {item['window_label']}: {item['requested_start']} to {item['requested_end']} ({item['market_context']})"
            )
    (output_root / "subperiod_coverage_note.md").write_text(
        "\n".join(coverage_lines) + "\n", encoding="utf-8"
    )
    (output_root / "subperiod_coverage_note.json").write_text(
        json.dumps(coverage, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": True,
                "run_id": str(args.run_id),
                "window_count": len(_SUBPERIOD_WINDOWS),
                "row_count": int(len(df)),
                "output_root": str(output_root),
                "available_start": coverage["available_start"],
                "available_end": coverage["available_end"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
