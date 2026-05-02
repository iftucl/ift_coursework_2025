from __future__ import annotations

"""Validate loaded pipeline data with consistent date typing across joins."""

import argparse
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

# Ensure script execution resolves local project modules without requiring PYTHONPATH.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.db import get_db_engine  # noqa: E402
from modules.output.data_contract import ALLOWED_FREQUENCIES, ALLOWED_SOURCES  # noqa: E402
from modules.transform.factors import (  # noqa: E402
    _resolve_latest_paired_financial_rows,
    _to_float_or_none,
)

DEFAULT_COVERAGE_FACTORS = {"sentiment_30d_avg", "article_count_30d"}
OPTIONAL_NULL_FACTORS = {"open_price", "high_price", "low_price", "daily_volume"}


def _normalize_date_column(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    if column not in frame.columns:
        return frame
    frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.date
    return frame


def _load_latest_run_id() -> Optional[str]:
    engine = get_db_engine()
    with engine.connect() as conn:
        row = conn.execute(text("""
                SELECT run_id
                FROM systematic_equity.pipeline_runs
                ORDER BY created_at DESC
                LIMIT 1
                """)).first()
    return str(row[0]) if row else None


def _load_factor_observations(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    engine = get_db_engine()
    with engine.connect() as conn:
        if start_date and end_date:
            df = pd.read_sql(
                text("""
                    SELECT
                        symbol,
                        observation_date,
                        factor_name,
                        factor_value,
                        source,
                        metric_frequency
                    FROM systematic_equity.factor_observations
                    WHERE observation_date BETWEEN :start_date AND :end_date
                    """),
                conn,
                params={
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                },
            )
        else:
            df = pd.read_sql(
                text("""
                    SELECT
                        symbol,
                        observation_date,
                        factor_name,
                        factor_value,
                        source,
                        metric_frequency
                    FROM systematic_equity.factor_observations
                    """),
                conn,
            )
    return _normalize_date_column(df, "observation_date")


def _daily_return_null_quality(
    factors: pd.DataFrame,
) -> tuple[set[tuple[str, object]], int, int]:
    """Return (expected_null_keys, expected_null_rows, unexpected_null_rows)."""
    if factors.empty:
        return set(), 0, 0

    daily_ret = factors[factors["factor_name"] == "daily_return"][
        ["symbol", "observation_date", "factor_value"]
    ].copy()
    if daily_ret.empty:
        return set(), 0, 0

    daily_ret_null = daily_ret[daily_ret["factor_value"].isna()].copy()
    if daily_ret_null.empty:
        return set(), 0, 0

    close_df = factors[factors["factor_name"] == "adjusted_close_price"][
        ["symbol", "observation_date", "factor_value"]
    ].copy()
    close_df["factor_value"] = pd.to_numeric(close_df["factor_value"], errors="coerce")
    close_df = (
        close_df.sort_values(["symbol", "observation_date"])
        .drop_duplicates(subset=["symbol", "observation_date"], keep="last")
        .rename(columns={"factor_value": "adjusted_close_price"})
    )
    close_df["prev_close"] = close_df.groupby("symbol")["adjusted_close_price"].shift(1)

    merged = daily_ret_null.merge(
        close_df[["symbol", "observation_date", "adjusted_close_price", "prev_close"]],
        on=["symbol", "observation_date"],
        how="left",
    )
    explainable = (
        merged["adjusted_close_price"].isna()
        | (merged["adjusted_close_price"] <= 0)
        | merged["prev_close"].isna()
        | (merged["prev_close"] <= 0)
    )
    expected_rows = merged[explainable][["symbol", "observation_date"]]
    expected_null_keys = set(map(tuple, expected_rows.itertuples(index=False, name=None)))
    expected_null_rows = int(explainable.sum())
    unexpected_null_rows = int((~explainable).sum())
    return expected_null_keys, expected_null_rows, unexpected_null_rows


def _validate_common_quality(
    factors: pd.DataFrame, daily_return_sanity_threshold: float
) -> tuple[dict[str, int], dict[str, int]]:
    if factors.empty:
        return (
            {
                "checked_rows": 0,
                "duplicate_key_rows": 0,
                "missing_required_rows": 0,
                "non_finite_value_rows": 0,
                "invalid_frequency_rows": 0,
                "invalid_source_rows": 0,
                "unexpected_daily_return_null_rows": 0,
                "news_sentiment_null_rows": 0,
                "news_count_null_rows": 0,
                "news_count_negative_rows": 0,
                "sentiment_30d_null_rows": 0,
            },
            {"daily_return_extreme_rows": 0, "expected_daily_return_null_rows": 0},
        )

    key_cols = ["symbol", "observation_date", "factor_name"]
    duplicate_key_rows = int(factors.duplicated(subset=key_cols, keep=False).sum())

    symbol_blank = factors["symbol"].isna() | (factors["symbol"].astype(str).str.strip() == "")
    factor_blank = factors["factor_name"].isna() | (
        factors["factor_name"].astype(str).str.strip() == ""
    )
    value_null = factors["factor_value"].isna()
    (
        expected_null_keys,
        expected_null_rows,
        unexpected_null_rows,
    ) = _daily_return_null_quality(factors)
    daily_return_null = value_null & (factors["factor_name"] == "daily_return")
    optional_market_null = value_null & factors["factor_name"].isin(OPTIONAL_NULL_FACTORS)
    row_keys = list(zip(factors["symbol"], factors["observation_date"]))
    explainable_daily_return_null = pd.Series(
        [k in expected_null_keys for k in row_keys], index=factors.index
    )
    null_value_allowed = daily_return_null & explainable_daily_return_null
    missing_required_rows = int(
        (
            symbol_blank
            | factors["observation_date"].isna()
            | factor_blank
            | (value_null & ~null_value_allowed & ~optional_market_null)
        ).sum()
    )

    numeric_values = pd.to_numeric(factors["factor_value"], errors="coerce")
    non_finite_mask = (~value_null) & (
        numeric_values.isna() | (~np.isfinite(numeric_values.to_numpy()))
    )
    non_finite_value_rows = int(non_finite_mask.sum())

    freq = factors["metric_frequency"].astype(str).str.strip().str.lower()
    invalid_frequency_rows = int((~freq.isin(ALLOWED_FREQUENCIES)).sum())

    src = factors["source"].astype(str).str.strip().str.lower()
    invalid_source_rows = int((~src.isin(ALLOWED_SOURCES)).sum())

    daily_ret = factors[factors["factor_name"] == "daily_return"].copy()
    daily_ret["factor_value"] = pd.to_numeric(daily_ret["factor_value"], errors="coerce")
    daily_return_extreme_rows = int(
        daily_ret["factor_value"].abs().gt(daily_return_sanity_threshold).fillna(False).sum()
    )
    news_sentiment = factors[factors["factor_name"] == "news_sentiment_daily"].copy()
    news_count = factors[factors["factor_name"] == "news_article_count_daily"].copy()
    sentiment_30d = factors[factors["factor_name"] == "sentiment_30d_avg"].copy()

    news_sentiment_null_rows = int(news_sentiment["factor_value"].isna().sum())
    news_count_null_rows = int(news_count["factor_value"].isna().sum())
    news_count["factor_value"] = pd.to_numeric(news_count["factor_value"], errors="coerce")
    news_count_negative_rows = int(news_count["factor_value"].lt(0).fillna(False).sum())
    sentiment_30d_null_rows = int(sentiment_30d["factor_value"].isna().sum())

    hard_fail_counts = {
        "checked_rows": int(len(factors)),
        "duplicate_key_rows": duplicate_key_rows,
        "missing_required_rows": missing_required_rows,
        "non_finite_value_rows": non_finite_value_rows,
        "invalid_frequency_rows": invalid_frequency_rows,
        "invalid_source_rows": invalid_source_rows,
        "unexpected_daily_return_null_rows": unexpected_null_rows,
        "news_sentiment_null_rows": news_sentiment_null_rows,
        "news_count_null_rows": news_count_null_rows,
        "news_count_negative_rows": news_count_negative_rows,
        "sentiment_30d_null_rows": sentiment_30d_null_rows,
    }
    warning_counts = {
        "daily_return_extreme_rows": daily_return_extreme_rows,
        "expected_daily_return_null_rows": expected_null_rows,
    }
    return hard_fail_counts, warning_counts


def _validate_daily_symbol_coverage(
    factors: pd.DataFrame,
    start_date: date,
    end_date: date,
    coverage_factors: set[str],
) -> dict[str, int]:
    if factors.empty or not coverage_factors:
        return {
            "coverage_expected_rows": 0,
            "coverage_missing_rows": 0,
            "coverage_trailing_unavailable_days": 0,
        }

    f = factors[
        factors["factor_name"].isin(coverage_factors) & factors["observation_date"].notna()
    ][["symbol", "observation_date", "factor_name"]].copy()
    if f.empty:
        return {
            "coverage_expected_rows": 0,
            "coverage_missing_rows": 0,
            "coverage_trailing_unavailable_days": 0,
        }

    symbols = sorted(set(f["symbol"].dropna().astype(str)))
    if not symbols:
        return {
            "coverage_expected_rows": 0,
            "coverage_missing_rows": 0,
            "coverage_trailing_unavailable_days": 0,
        }

    latest_observed_date = max(f["observation_date"])
    effective_end_date = min(end_date, latest_observed_date)
    trailing_unavailable_days = max(0, int((end_date - effective_end_date).days))
    if effective_end_date < start_date:
        return {
            "coverage_expected_rows": 0,
            "coverage_missing_rows": 0,
            "coverage_trailing_unavailable_days": trailing_unavailable_days,
        }

    full_dates = pd.date_range(start_date, effective_end_date, freq="D").date
    if len(full_dates) == 0:
        return {
            "coverage_expected_rows": 0,
            "coverage_missing_rows": 0,
            "coverage_trailing_unavailable_days": trailing_unavailable_days,
        }

    expected_rows = len(symbols) * len(full_dates) * len(coverage_factors)

    grid = pd.MultiIndex.from_product(
        [symbols, full_dates, sorted(coverage_factors)],
        names=["symbol", "observation_date", "factor_name"],
    )
    observed = (
        f.assign(symbol=f["symbol"].astype(str))
        .drop_duplicates(subset=["symbol", "observation_date", "factor_name"], keep="last")
        .set_index(["symbol", "observation_date", "factor_name"])
    )
    missing_rows = int(len(grid.difference(observed.index)))
    return {
        "coverage_expected_rows": expected_rows,
        "coverage_missing_rows": missing_rows,
        "coverage_trailing_unavailable_days": trailing_unavailable_days,
    }


def _validate_daily_return(
    tolerance: float,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[int, float]:
    engine = get_db_engine()
    with engine.connect() as conn:
        if start_date and end_date:
            query_start = start_date - timedelta(days=7)
            price = pd.read_sql(
                text("""
                    SELECT symbol, observation_date, factor_name, factor_value
                    FROM systematic_equity.factor_observations
                    WHERE factor_name IN ('adjusted_close_price', 'daily_return')
                      AND observation_date BETWEEN :query_start AND :end_date
                    ORDER BY symbol, observation_date
                    """),
                conn,
                params={
                    "query_start": query_start.isoformat(),
                    "end_date": end_date.isoformat(),
                },
            )
        else:
            price = pd.read_sql(
                text("""
                    SELECT symbol, observation_date, factor_name, factor_value
                    FROM systematic_equity.factor_observations
                    WHERE factor_name IN ('adjusted_close_price', 'daily_return')
                    ORDER BY symbol, observation_date
                    """),
                conn,
            )

    if price.empty:
        return 0, 0.0

    price = _normalize_date_column(price, "observation_date")
    piv = (
        price.pivot_table(
            index=["symbol", "observation_date"],
            columns="factor_name",
            values="factor_value",
            aggfunc="last",
        )
        .reset_index()
        .sort_values(["symbol", "observation_date"])
    )

    piv["adjusted_close_price"] = pd.to_numeric(piv["adjusted_close_price"], errors="coerce")
    piv["daily_return"] = pd.to_numeric(piv["daily_return"], errors="coerce")
    piv["prev_close"] = piv.groupby("symbol")["adjusted_close_price"].shift(1)

    valid = piv[
        (piv["adjusted_close_price"] > 0)
        & (piv["prev_close"] > 0)
        & piv["daily_return"].notna()
        & piv["observation_date"].notna()
    ].copy()
    if start_date and end_date:
        valid = valid[
            (valid["observation_date"] >= start_date) & (valid["observation_date"] <= end_date)
        ].copy()
    if valid.empty:
        return 0, 0.0

    valid["recalc"] = (valid["adjusted_close_price"] / valid["prev_close"]).map(math.log)
    valid["abs_err"] = (valid["daily_return"] - valid["recalc"]).abs()
    max_abs_err = float(valid["abs_err"].max())
    if max_abs_err > tolerance:
        worst = valid.sort_values("abs_err", ascending=False).head(5)[
            ["symbol", "observation_date", "daily_return", "recalc", "abs_err"]
        ]
        raise AssertionError(
            "daily_return check failed. max_abs_err="
            f"{max_abs_err:.10f} > tolerance={tolerance}. "
            f"worst_rows=\n{worst.to_string(index=False)}"
        )
    return int(len(valid)), max_abs_err


def _validate_debt_to_equity(
    tolerance: float,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[int, float]:
    engine = get_db_engine()
    with engine.connect() as conn:
        if end_date:
            atomics = pd.read_sql(
                text("""
                    SELECT
                        symbol,
                        report_date AS observation_date,
                        metric_name,
                        metric_value,
                        source,
                        COALESCE(publish_date, as_of, report_date) AS publish_date
                    FROM systematic_equity.financial_observations
                    WHERE metric_name IN ('total_debt', 'total_shareholder_equity')
                      AND report_date <= :end_date
                    ORDER BY symbol, report_date, metric_name
                    """),
                conn,
                params={"end_date": end_date.isoformat()},
            )
        else:
            atomics = pd.read_sql(
                text("""
                    SELECT
                        symbol,
                        report_date AS observation_date,
                        metric_name,
                        metric_value,
                        source,
                        COALESCE(publish_date, as_of, report_date) AS publish_date
                    FROM systematic_equity.financial_observations
                    WHERE metric_name IN ('total_debt', 'total_shareholder_equity')
                    ORDER BY symbol, report_date, metric_name
                    """),
                conn,
            )
        if start_date and end_date:
            dte = pd.read_sql(
                text("""
                    SELECT symbol, observation_date, factor_value
                    FROM systematic_equity.factor_observations
                    WHERE factor_name = 'debt_to_equity'
                      AND observation_date BETWEEN :start_date AND :end_date
                    ORDER BY symbol, observation_date
                    """),
                conn,
                params={
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                },
            )
        else:
            dte = pd.read_sql(
                text("""
                    SELECT symbol, observation_date, factor_value
                    FROM systematic_equity.factor_observations
                    WHERE factor_name = 'debt_to_equity'
                    ORDER BY symbol, observation_date
                    """),
                conn,
            )

    if atomics.empty or dte.empty:
        return 0, 0.0

    atomics = _normalize_date_column(atomics, "observation_date")
    atomics = _normalize_date_column(atomics, "publish_date")
    dte = _normalize_date_column(dte, "observation_date")

    atomics["metric_value"] = pd.to_numeric(atomics["metric_value"], errors="coerce")
    dte["factor_value"] = pd.to_numeric(dte["factor_value"], errors="coerce")

    debt = atomics[atomics["metric_name"] == "total_debt"][
        ["symbol", "observation_date", "metric_value", "publish_date", "source"]
    ].rename(columns={"metric_value": "debt"})
    equity = atomics[atomics["metric_name"] == "total_shareholder_equity"][
        ["symbol", "observation_date", "metric_value", "publish_date", "source"]
    ].rename(columns={"metric_value": "equity"})

    errs = []
    worst_rows = []
    checked = 0
    for symbol, group in dte.groupby("symbol"):
        debt_s = debt[debt["symbol"] == symbol].sort_values(["observation_date", "publish_date"])
        equity_s = equity[equity["symbol"] == symbol].sort_values(
            ["observation_date", "publish_date"]
        )
        if debt_s.empty or equity_s.empty:
            continue
        for row in group.itertuples(index=False):
            cutoff = row.observation_date
            if cutoff is None:
                continue
            debt_row, equity_row, pair_meta = _resolve_latest_paired_financial_rows(
                debt_s,
                equity_s,
                cutoff=cutoff,
                factor="debt_to_equity",
                symbol=symbol,
                left_metric="total_debt",
                right_metric="total_shareholder_equity",
            )
            if debt_row is None or equity_row is None:
                continue
            debt_value = _to_float_or_none(debt_row.get("debt"))
            equity_value = _to_float_or_none(equity_row.get("equity"))
            observed = _to_float_or_none(row.factor_value)
            if debt_value is None or equity_value is None or observed is None or equity_value <= 0:
                continue
            expected = float(debt_value / equity_value)
            if not math.isfinite(expected):
                continue
            abs_err = abs(observed - expected)
            errs.append(abs_err)
            worst_rows.append(
                {
                    "symbol": symbol,
                    "observation_date": cutoff.isoformat(),
                    "observed": observed,
                    "recalc": expected,
                    "abs_err": abs_err,
                    "pair_mode": None if pair_meta is None else pair_meta.get("pair_mode"),
                    "report_date": None
                    if pair_meta is None or pair_meta.get("effective_report_date") is None
                    else pair_meta["effective_report_date"].isoformat(),
                    "publish_date": None
                    if pair_meta is None or pair_meta.get("effective_publish_date") is None
                    else pair_meta["effective_publish_date"].isoformat(),
                    "debt_source": debt_row.get("source"),
                    "equity_source": equity_row.get("source"),
                }
            )
            checked += 1

    if not errs:
        return 0, 0.0

    max_abs_err = float(max(errs))
    if max_abs_err > tolerance:
        worst = pd.DataFrame(worst_rows).sort_values("abs_err", ascending=False).head(5)[
            [
                "symbol",
                "observation_date",
                "observed",
                "recalc",
                "abs_err",
                "pair_mode",
                "report_date",
                "publish_date",
                "debt_source",
                "equity_source",
            ]
        ]
        raise AssertionError(
            "debt_to_equity check failed. max_abs_err="
            f"{max_abs_err:.10f} > tolerance={tolerance}. "
            f"worst_rows=\n{worst.to_string(index=False)}"
        )
    return checked, max_abs_err


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate loaded pipeline data consistency.")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1e-6,
        help="Maximum accepted absolute error for recompute checks.",
    )
    parser.add_argument(
        "--daily-return-sanity-threshold",
        type=float,
        default=1.0,
        help="Absolute threshold for daily_return sanity warnings (does not fail).",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Coverage check start date (YYYY-MM-DD). Use together with --end-date.",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="Coverage check end date (YYYY-MM-DD). Use together with --start-date.",
    )
    parser.add_argument(
        "--coverage-factors",
        type=str,
        default="sentiment_30d_avg,article_count_30d",
        help="Comma-separated factors for optional daily coverage check.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if (args.start_date is None) ^ (args.end_date is None):
        raise ValueError("--start-date and --end-date must be provided together.")
    start_date: date | None = None
    end_date: date | None = None
    if args.start_date and args.end_date:
        start_date = pd.to_datetime(args.start_date, errors="raise").date()
        end_date = pd.to_datetime(args.end_date, errors="raise").date()
        if start_date > end_date:
            raise ValueError("--start-date must be <= --end-date.")
    coverage_factors = {
        x.strip() for x in str(args.coverage_factors).split(",") if x.strip()
    } or set(DEFAULT_COVERAGE_FACTORS)

    latest_run_id = _load_latest_run_id()
    print(f"latest_run_id={latest_run_id}")
    if start_date and end_date:
        print(f"validation_scope={start_date.isoformat()}..{end_date.isoformat()}")
    else:
        print("validation_scope=all_history")

    validation_kwargs = (
        {"start_date": start_date, "end_date": end_date}
        if start_date and end_date
        else {}
    )

    n_ret, err_ret = _validate_daily_return(args.tolerance, **validation_kwargs)
    print(f"daily_return_checked_rows={n_ret} max_abs_err={err_ret:.10f}")

    n_dte, err_dte = _validate_debt_to_equity(args.tolerance, **validation_kwargs)
    print(f"debt_to_equity_checked_rows={n_dte} max_abs_err={err_dte:.10f}")

    factors = _load_factor_observations(**validation_kwargs)
    hard_fail_counts, warning_counts = _validate_common_quality(
        factors, daily_return_sanity_threshold=args.daily_return_sanity_threshold
    )
    print(
        "common_quality_checked_rows="
        f"{hard_fail_counts['checked_rows']} "
        f"duplicate_key_rows={hard_fail_counts['duplicate_key_rows']} "
        f"missing_required_rows={hard_fail_counts['missing_required_rows']} "
        f"non_finite_value_rows={hard_fail_counts['non_finite_value_rows']} "
        f"invalid_frequency_rows={hard_fail_counts['invalid_frequency_rows']} "
        f"invalid_source_rows={hard_fail_counts['invalid_source_rows']} "
        "unexpected_daily_return_null_rows="
        f"{hard_fail_counts['unexpected_daily_return_null_rows']} "
        f"news_sentiment_null_rows={hard_fail_counts['news_sentiment_null_rows']} "
        f"news_count_null_rows={hard_fail_counts['news_count_null_rows']} "
        f"news_count_negative_rows={hard_fail_counts['news_count_negative_rows']} "
        f"sentiment_30d_null_rows={hard_fail_counts['sentiment_30d_null_rows']}"
    )
    print(
        "warning_daily_return_extreme_rows="
        f"{warning_counts['daily_return_extreme_rows']} "
        "expected_daily_return_null_rows="
        f"{warning_counts['expected_daily_return_null_rows']} "
        f"threshold={args.daily_return_sanity_threshold:.6f}"
    )

    hard_fail_total = sum(v for k, v in hard_fail_counts.items() if k != "checked_rows")
    if hard_fail_total > 0:
        raise AssertionError(
            "common quality checks failed: " f"{hard_fail_counts}, warnings={warning_counts}"
        )

    if start_date and end_date:
        coverage = _validate_daily_symbol_coverage(
            factors,
            start_date=start_date,
            end_date=end_date,
            coverage_factors=coverage_factors,
        )
        print(
            f"coverage_date_range={start_date.isoformat()}..{end_date.isoformat()} "
            f"coverage_factors={','.join(sorted(coverage_factors))} "
            f"coverage_expected_rows={coverage['coverage_expected_rows']} "
            f"coverage_missing_rows={coverage['coverage_missing_rows']} "
            "coverage_trailing_unavailable_days="
            f"{coverage.get('coverage_trailing_unavailable_days', 0)}"
        )
        if coverage["coverage_missing_rows"] > 0:
            raise AssertionError(f"coverage check failed: {coverage}")

    print("validation_status=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
