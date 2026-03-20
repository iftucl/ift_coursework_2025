from __future__ import annotations

import csv
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List

import Main
from modules.output.normalize import normalize_financial_records, normalize_records
from modules.output.quality import run_quality_checks
from modules.transform.factors import compute_final_factor_records

RUN_DATE = "2026-02-10"
BACKFILL_YEARS = 1
SNAPSHOT_PATH = Path(__file__).resolve().parent / "fixtures" / "golden_final_factors_snapshot.csv"


def _business_days(start: date, end: date) -> List[date]:
    out: List[date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            out.append(cur)
        cur += timedelta(days=1)
    return out


def _build_replay_raw_records() -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    start = date(2026, 1, 1)
    end = date(2026, 2, 10)
    bdays = _business_days(start, end)

    for i, d in enumerate(bdays):
        ds = d.isoformat()
        if ds != RUN_DATE:
            records.append(
                {
                    "symbol": "AAA",
                    "observation_date": ds,
                    "factor_name": "adjusted_close_price",
                    "value": 100.0 + float(i),
                    "source": "alpha_vantage",
                    "frequency": "daily",
                    "source_report_date": ds,
                }
            )
        # Create >3-trading-day price gap for BBB near run_date.
        if d < date(2026, 2, 5):
            records.append(
                {
                    "symbol": "BBB",
                    "observation_date": ds,
                    "factor_name": "adjusted_close_price",
                    "value": 60.0 + float(i),
                    "source": "alpha_vantage",
                    "frequency": "daily",
                    "source_report_date": ds,
                }
            )

    # Add malformed/invalid rows to exercise NaN coercion and global filtering.
    records.append(
        {
            "symbol": "AAA",
            "observation_date": "2026-01-20",
            "factor_name": "adjusted_close_price",
            "value": "bad-number",
            "source": "alpha_vantage",
            "frequency": "daily",
            "source_report_date": "2026-01-20",
        }
    )
    records.append(
        {
            "symbol": None,
            "observation_date": "2026-01-21",
            "factor_name": "adjusted_close_price",
            "value": 123.0,
            "source": "alpha_vantage",
            "frequency": "daily",
            "source_report_date": "2026-01-21",
        }
    )
    records.append(
        {
            "symbol": "AAA",
            "observation_date": None,
            "factor_name": "adjusted_close_price",
            "value": 123.0,
            "source": "alpha_vantage",
            "frequency": "daily",
            "source_report_date": "2026-01-21",
        }
    )

    # Dividends for dividend_yield.
    records.extend(
        [
            {
                "symbol": "AAA",
                "observation_date": "2025-11-15",
                "factor_name": "dividend_per_share",
                "value": 1.0,
                "source": "alpha_vantage",
                "frequency": "daily",
                "source_report_date": "2025-11-15",
            },
            {
                "symbol": "AAA",
                "observation_date": "2026-01-15",
                "factor_name": "dividend_per_share",
                "value": "",
                "source": "alpha_vantage",
                "frequency": "daily",
                "source_report_date": "2026-01-15",
            },
            {
                "symbol": "AAA",
                "observation_date": "2026-02-01",
                "factor_name": "dividend_per_share",
                "value": 0.5,
                "source": "alpha_vantage",
                "frequency": "daily",
                "source_report_date": "2026-02-01",
            },
            {
                "symbol": "BBB",
                "observation_date": "2025-12-20",
                "factor_name": "dividend_per_share",
                "value": 0.3,
                "source": "alpha_vantage",
                "frequency": "daily",
                "source_report_date": "2025-12-20",
            },
        ]
    )

    # Financial atomics (quarterly).
    def _fin(symbol: str, report_date: str, factor: str, value: Any) -> Dict[str, Any]:
        return {
            "symbol": symbol,
            "observation_date": report_date,
            "factor_name": factor,
            "value": value,
            "source": "alpha_vantage",
            "frequency": "quarterly",
            "source_report_date": report_date,
            "report_date": report_date,
            "as_of": RUN_DATE,
            "period_type": "quarterly",
            "currency": "USD",
            "metric_definition": "provider_reported",
        }

    # AAA: stale-but-usable filings (between 270 and 365 days old).
    records.extend(
        [
            _fin("AAA", "2025-05-15", "shares_outstanding", 10.0),
            _fin("AAA", "2025-05-15", "total_shareholder_equity", 200.0),
            _fin("AAA", "2025-05-15", "total_debt", 50.0),
            _fin("AAA", "2025-05-15", "enterprise_ebitda", 40.0),
            _fin("AAA", "2025-05-15", "enterprise_revenue", 100.0),
        ]
    )

    # BBB: expired PB inputs, and invalid denominators for ratio guards.
    records.extend(
        [
            _fin("BBB", "2025-02-09", "shares_outstanding", 8.0),
            _fin("BBB", "2025-02-09", "total_shareholder_equity", 120.0),
            _fin("BBB", "2026-01-31", "total_debt", 30.0),
            _fin("BBB", "2026-01-31", "total_shareholder_equity", 0.0),
            _fin("BBB", "2026-01-31", "enterprise_ebitda", 12.0),
            _fin("BBB", "2026-01-31", "enterprise_revenue", 0.0),
        ]
    )

    # News atomics to test zero-fill and invalid row drops.
    records.extend(
        [
            {
                "symbol": "AAA",
                "observation_date": "2025-12-15",
                "factor_name": "news_sentiment_daily",
                "value": 0.9,
                "source": "extractor_b",
                "frequency": "daily",
                "source_report_date": "2025-12-15",
            },
            {
                "symbol": "AAA",
                "observation_date": "2025-12-15",
                "factor_name": "news_article_count_daily",
                "value": 2.0,
                "source": "extractor_b",
                "frequency": "daily",
                "source_report_date": "2025-12-15",
            },
            {
                "symbol": "AAA",
                "observation_date": "bad-date",
                "factor_name": "news_article_count_daily",
                "value": "x",
                "source": "extractor_b",
                "frequency": "daily",
                "source_report_date": "bad-date",
            },
            {
                "symbol": "BBB",
                "observation_date": "2026-02-05",
                "factor_name": "news_sentiment_daily",
                "value": -0.5,
                "source": "extractor_b",
                "frequency": "daily",
                "source_report_date": "2026-02-05",
            },
            {
                "symbol": "BBB",
                "observation_date": "2026-02-05",
                "factor_name": "news_article_count_daily",
                "value": 1.0,
                "source": "extractor_b",
                "frequency": "daily",
                "source_report_date": "2026-02-05",
            },
            {
                "symbol": "BBB",
                "observation_date": "2026-02-05",
                "factor_name": "news_sentiment_daily",
                "value": "not-a-number",
                "source": "extractor_b",
                "frequency": "daily",
                "source_report_date": "2026-02-05",
            },
        ]
    )
    return records


def _build_replay_atomic_records() -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    raw = _build_replay_raw_records()
    financial_raw, non_financial_raw = Main.split_atomic_financial_records(raw)
    normalized_atomic = normalize_records(non_financial_raw)
    normalized_financial = normalize_financial_records(financial_raw)
    quality = run_quality_checks(normalized_atomic)

    atomic_records: List[Dict[str, Any]] = list(normalized_atomic)
    for row in normalized_financial:
        atomic_records.append(
            {
                "symbol": row.get("symbol"),
                "observation_date": row.get("report_date"),
                "factor_name": row.get("metric_name"),
                "factor_value": row.get("metric_value"),
                "source": row.get("source"),
                "metric_frequency": row.get("period_type"),
                "source_report_date": row.get("report_date"),
            }
        )
    return atomic_records, {"quality": quality}


def _compute_final_records() -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    atomic_records, meta = _build_replay_atomic_records()
    final = compute_final_factor_records(
        atomic_records=atomic_records,
        run_date=RUN_DATE,
        backfill_years=BACKFILL_YEARS,
        output_frequency="daily",
    )
    return final, meta


def _snapshot_rows(final_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    keep_factors = {
        "dividend_yield",
        "pb_ratio",
        "debt_to_equity",
        "ebitda_margin",
        "momentum_1m",
        "volatility_20d",
        "sentiment_30d_avg",
        "article_count_30d",
    }
    keep_dates = {"2026-02-07", "2026-02-10"}
    rows = [
        {
            "symbol": str(r.get("symbol") or ""),
            "observation_date": str(r.get("observation_date") or ""),
            "factor_name": str(r.get("factor_name") or ""),
            "factor_value": float(r.get("factor_value")),
            "source_report_date": str(r.get("source_report_date") or ""),
        }
        for r in final_records
        if str(r.get("factor_name") or "") in keep_factors
        and str(r.get("observation_date") or "") in keep_dates
    ]
    rows.sort(
        key=lambda r: (
            r["symbol"],
            r["observation_date"],
            r["factor_name"],
            r["source_report_date"],
        )
    )
    return rows


def _load_snapshot_rows() -> List[Dict[str, Any]]:
    with SNAPSHOT_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows: List[Dict[str, Any]] = []
        for r in reader:
            rows.append(
                {
                    "symbol": str(r["symbol"]),
                    "observation_date": str(r["observation_date"]),
                    "factor_name": str(r["factor_name"]),
                    "factor_value": float(r["factor_value"]),
                    "source_report_date": str(r["source_report_date"]),
                }
            )
    return rows


def test_offline_replay_e2e_chain_covers_key_boundary_rules():
    final_records, meta = _compute_final_records()
    quality = meta["quality"]

    # malformed raw rows are present and should be surfaced before transform.
    assert quality["missing_required"] >= 1

    by_key = {(r["symbol"], r["observation_date"], r["factor_name"]): r for r in final_records}

    # price lookback <= 3 trading-day records: AAA can still compute on run_date.
    assert ("AAA", RUN_DATE, "dividend_yield") in by_key
    assert ("AAA", RUN_DATE, "pb_ratio") in by_key

    # BBB has >3 trading-day gap near run_date and expired PB filings: no output.
    assert ("BBB", RUN_DATE, "dividend_yield") not in by_key
    assert ("BBB", RUN_DATE, "pb_ratio") not in by_key

    # denominator guards (equity/revenue <= 0) should suppress ratio outputs.
    assert ("BBB", RUN_DATE, "debt_to_equity") not in by_key
    assert ("BBB", RUN_DATE, "ebitda_margin") not in by_key

    # no-news trailing 30D for AAA should be explicit zeros.
    assert by_key[("AAA", RUN_DATE, "sentiment_30d_avg")]["factor_value"] == 0.0
    assert by_key[("AAA", RUN_DATE, "article_count_30d")]["factor_value"] == 0.0

    # transformed outputs must remain finite after NaN/Inf filtering.
    for row in final_records:
        v = float(row["factor_value"])
        assert math.isfinite(v)
        assert str(row.get("symbol") or "").strip()
        assert str(row.get("factor_name") or "").strip()
        assert str(row.get("observation_date") or "").strip()


def test_golden_snapshot_regression_for_final_factor_outputs():
    final_records, _ = _compute_final_records()
    actual = _snapshot_rows(final_records)
    expected = _load_snapshot_rows()

    assert len(actual) == len(expected)
    for a, e in zip(actual, expected):
        assert a["symbol"] == e["symbol"]
        assert a["observation_date"] == e["observation_date"]
        assert a["factor_name"] == e["factor_name"]
        assert a["source_report_date"] == e["source_report_date"]
        assert abs(a["factor_value"] - e["factor_value"]) <= 1e-8
