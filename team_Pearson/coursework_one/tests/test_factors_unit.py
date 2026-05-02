from __future__ import annotations

from modules.transform import factors


def test_compute_final_factor_records_dividend_yield_daily_asof():
    atomic = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-01-30",
            "factor_name": "adjusted_close_price",
            "factor_value": 100.0,
        },
        {
            "symbol": "AAPL",
            "observation_date": "2025-12-15",
            "factor_name": "dividend_per_share",
            "factor_value": 1.2,
        },
        {
            "symbol": "AAPL",
            "observation_date": "2025-09-15",
            "factor_name": "dividend_per_share",
            "factor_value": 0.8,
        },
    ]
    out = factors.compute_final_factor_records(atomic, run_date="2026-01-31", backfill_years=1)
    dy = [r for r in out if r["factor_name"] == "dividend_yield"]
    assert len(dy) >= 1
    by_date = {r["observation_date"]: r for r in dy}
    assert "2026-01-31" in by_date
    assert abs(by_date["2026-01-31"]["factor_value"] - 0.02) < 1e-9
    assert by_date["2026-01-31"]["metric_frequency"] == "daily"
    assert by_date["2026-01-31"]["publish_date"] == "2026-01-31"


def test_compute_final_factor_records_pb_de_ebitda():
    atomic = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-31",
            "factor_name": "adjusted_close_price",
            "factor_value": 50.0,
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-31",
            "factor_name": "shares_outstanding",
            "factor_value": 100.0,
            "source_report_date": "2026-03-31",
            "source": "edgar",
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-31",
            "factor_name": "total_shareholder_equity",
            "factor_value": 1000.0,
            "source_report_date": "2026-03-31",
            "source": "edgar",
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-31",
            "factor_name": "book_value",
            "factor_value": 1000.0,
            "source_report_date": "2026-03-31",
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-31",
            "factor_name": "total_debt",
            "factor_value": 300.0,
            "source_report_date": "2026-03-31",
            "source": "edgar",
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-31",
            "factor_name": "enterprise_ebitda",
            "factor_value": 200.0,
            "source_report_date": "2026-03-31",
            "source": "edgar",
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-31",
            "factor_name": "enterprise_revenue",
            "factor_value": 1000.0,
            "source_report_date": "2026-03-31",
            "source": "edgar",
        },
    ]
    out = factors.compute_final_factor_records(atomic, run_date="2026-03-31", backfill_years=1)
    names = {r["factor_name"] for r in out}
    assert "pb_ratio" in names
    assert "debt_to_equity" in names
    assert "ebitda_margin" in names


def test_debt_to_equity_is_daily_asof_aligned():
    atomic = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-01-10",
            "factor_name": "total_debt",
            "factor_value": 300.0,
            "source_report_date": "2026-01-10",
            "source": "edgar",
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-01-10",
            "factor_name": "total_shareholder_equity",
            "factor_value": 100.0,
            "source_report_date": "2026-01-10",
            "source": "edgar",
        },
    ]
    out = factors.compute_final_factor_records(atomic, run_date="2026-01-15", backfill_years=1)
    dte = [r for r in out if r["factor_name"] == "debt_to_equity"]
    assert len(dte) == 6  # 2026-01-10 ... 2026-01-15
    assert all(r["metric_frequency"] == "daily" for r in dte)
    assert {r["factor_value"] for r in dte} == {3.0}
    assert {r["source_report_date"] for r in dte} == {"2026-01-10"}


def test_debt_to_equity_waits_for_financial_publish_date():
    atomic = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-01-10",
            "factor_name": "total_debt",
            "factor_value": 300.0,
            "source_report_date": "2026-01-10",
            "publish_date": "2026-01-13",
            "source": "edgar",
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-01-10",
            "factor_name": "total_shareholder_equity",
            "factor_value": 100.0,
            "source_report_date": "2026-01-10",
            "publish_date": "2026-01-13",
            "source": "edgar",
        },
    ]
    out = factors.compute_final_factor_records(atomic, run_date="2026-01-15", backfill_years=1)
    dte = [r for r in out if r["factor_name"] == "debt_to_equity"]
    assert [r["observation_date"] for r in dte] == ["2026-01-13", "2026-01-14", "2026-01-15"]


def test_ebitda_margin_is_daily_asof_aligned():
    atomic = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-01-10",
            "factor_name": "enterprise_ebitda",
            "factor_value": 200.0,
            "source_report_date": "2026-01-10",
            "source": "edgar",
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-01-10",
            "factor_name": "enterprise_revenue",
            "factor_value": 1000.0,
            "source_report_date": "2026-01-10",
            "source": "edgar",
        },
    ]
    out = factors.compute_final_factor_records(atomic, run_date="2026-01-15", backfill_years=1)
    em = [r for r in out if r["factor_name"] == "ebitda_margin"]
    assert len(em) == 6  # 2026-01-10 ... 2026-01-15
    assert all(r["metric_frequency"] == "daily" for r in em)
    assert {r["factor_value"] for r in em} == {0.2}
    assert {r["source_report_date"] for r in em} == {"2026-01-10"}


def test_output_frequency_monthly_samples_daily_asof_series():
    atomic = [
        {
            "symbol": "SYM1",
            "observation_date": "2026-01-10",
            "factor_name": "total_debt",
            "factor_value": 300.0,
            "source_report_date": "2026-01-10",
            "source": "edgar",
        },
        {
            "symbol": "SYM1",
            "observation_date": "2026-01-10",
            "factor_name": "total_shareholder_equity",
            "factor_value": 100.0,
            "source_report_date": "2026-01-10",
            "source": "edgar",
        },
    ]
    out = factors.compute_final_factor_records(
        atomic,
        run_date="2026-01-15",
        backfill_years=1,
        output_frequency="monthly",
    )
    dte = [r for r in out if r["factor_name"] == "debt_to_equity"]
    assert len(dte) == 1
    assert dte[0]["observation_date"] == "2026-01-15"
    assert dte[0]["factor_value"] == 3.0


def test_output_frequency_quarterly_samples_daily_asof_series():
    atomic = [
        {
            "symbol": "SYM1",
            "observation_date": "2026-01-10",
            "factor_name": "enterprise_ebitda",
            "factor_value": 200.0,
            "source_report_date": "2026-01-10",
            "source": "edgar",
        },
        {
            "symbol": "SYM1",
            "observation_date": "2026-01-10",
            "factor_name": "enterprise_revenue",
            "factor_value": 1000.0,
            "source_report_date": "2026-01-10",
            "source": "edgar",
        },
    ]
    out = factors.compute_final_factor_records(
        atomic,
        run_date="2026-01-15",
        backfill_years=1,
        output_frequency="quarterly",
    )
    em = [r for r in out if r["factor_name"] == "ebitda_margin"]
    assert len(em) == 1
    assert em[0]["observation_date"] == "2026-01-15"
    assert em[0]["factor_value"] == 0.2


def test_ebitda_margin_uses_available_enterprise_pair_without_period_basis_check():
    atomic = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-01-10",
            "factor_name": "enterprise_ebitda",
            "factor_value": 200.0,
            "source_report_date": "2026-01-10",
            "source": "edgar",
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-01-10",
            "factor_name": "enterprise_revenue",
            "factor_value": 1000.0,
            "source_report_date": "2026-01-10",
            "source": "edgar",
        },
    ]
    out = factors.compute_final_factor_records(atomic, run_date="2026-01-15", backfill_years=1)
    em = [r for r in out if r["factor_name"] == "ebitda_margin"]
    assert len(em) == 6
    assert {r["factor_value"] for r in em} == {0.2}


def test_debt_to_equity_uses_mixed_source_fallback_when_same_source_pair_is_unavailable():
    atomic = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-01-10",
            "factor_name": "total_debt",
            "factor_value": 300.0,
            "source_report_date": "2026-01-10",
            "source": "edgar",
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-01-10",
            "factor_name": "total_shareholder_equity",
            "factor_value": 100.0,
            "source_report_date": "2026-01-10",
            "source": "yfinance",
        },
    ]
    out = factors.compute_final_factor_records(atomic, run_date="2026-01-15", backfill_years=1)
    dte = [r for r in out if r["factor_name"] == "debt_to_equity"]
    assert len(dte) == 6
    assert {r["factor_value"] for r in dte} == {3.0}


def test_compute_final_factor_records_sentiment_with_zero_news_fallback():
    atomic = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-01-15",
            "factor_name": "news_sentiment_daily",
            "factor_value": 0.5,
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-01-16",
            "factor_name": "news_sentiment_daily",
            "factor_value": 0.1,
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-01-15",
            "factor_name": "news_article_count_daily",
            "factor_value": 1.0,
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-01-16",
            "factor_name": "news_article_count_daily",
            "factor_value": 1.0,
        },
    ]
    out = factors.compute_final_factor_records(atomic, run_date="2026-02-28", backfill_years=1)
    s = [r for r in out if r["factor_name"] == "sentiment_30d_avg"]
    c = [r for r in out if r["factor_name"] == "article_count_30d"]
    assert len(s) > 100
    assert len(c) > 100
    assert all(r["metric_frequency"] == "daily" for r in s)
    assert all(r["metric_frequency"] == "daily" for r in c)

    by_date = {r["observation_date"]: r for r in s}
    count_by_date = {r["observation_date"]: r for r in c}
    assert "2026-01-31" in by_date and "2026-01-31" in count_by_date
    assert "2026-02-28" in by_date and "2026-02-28" in count_by_date
    # Jan-31 includes two positive sentiment days in trailing 30D.
    assert abs(by_date["2026-01-31"]["factor_value"] - 0.02) < 1e-12
    assert count_by_date["2026-01-31"]["factor_value"] == 2.0
    assert by_date["2026-01-31"]["publish_date"] == "2026-01-31"
    assert count_by_date["2026-01-31"]["publish_date"] == "2026-01-31"
    # Feb-28 has no news in trailing 30D window -> zero fallback remains effective.
    assert by_date["2026-02-28"]["factor_value"] == 0.0
    assert count_by_date["2026-02-28"]["factor_value"] == 0.0
    assert by_date["2026-02-28"]["publish_date"] == "2026-02-28"
    assert count_by_date["2026-02-28"]["publish_date"] == "2026-02-28"


def test_compute_final_factor_records_generates_sentiment_7d_and_surprise():
    atomic = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-01-15",
            "factor_name": "news_sentiment_daily",
            "factor_value": 0.5,
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-01-16",
            "factor_name": "news_sentiment_daily",
            "factor_value": 0.1,
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-01-15",
            "factor_name": "news_article_count_daily",
            "factor_value": 1.0,
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-01-16",
            "factor_name": "news_article_count_daily",
            "factor_value": 1.0,
        },
    ]
    out = factors.compute_final_factor_records(atomic, run_date="2026-01-20", backfill_years=1)
    names = {r["factor_name"] for r in out}
    assert "sentiment_7d_avg" in names
    assert "sentiment_surprise" in names
    assert "article_count_7d" in names

    by_key = {(r["factor_name"], r["observation_date"]): r for r in out}
    avg7 = by_key[("sentiment_7d_avg", "2026-01-16")]["factor_value"]
    avg30 = by_key[("sentiment_30d_avg", "2026-01-16")]["factor_value"]
    surprise = by_key[("sentiment_surprise", "2026-01-16")]["factor_value"]
    count7 = by_key[("article_count_7d", "2026-01-16")]["factor_value"]
    assert abs(surprise - (avg7 - avg30)) < 1e-12
    assert count7 == 2.0
    assert by_key[("sentiment_7d_avg", "2026-01-16")]["publish_date"] == "2026-01-16"
    assert by_key[("sentiment_surprise", "2026-01-16")]["publish_date"] == "2026-01-16"
    assert by_key[("article_count_7d", "2026-01-16")]["publish_date"] == "2026-01-16"


def test_compute_final_factor_records_ep_ratio_falls_back_to_net_income_over_shares():
    atomic = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-31",
            "factor_name": "adjusted_close_price",
            "factor_value": 50.0,
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-31",
            "factor_name": "net_income",
            "factor_value": 200.0,
            "source_report_date": "2026-03-31",
            "publish_date": "2026-03-31",
            "source": "edgar",
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-31",
            "factor_name": "shares_outstanding",
            "factor_value": 100.0,
            "source_report_date": "2026-03-31",
            "publish_date": "2026-03-31",
            "source": "edgar",
        },
    ]
    out = factors.compute_final_factor_records(atomic, run_date="2026-03-31", backfill_years=1)
    ep = [
        r for r in out if r["factor_name"] == "ep_ratio" and r["observation_date"] == "2026-03-31"
    ]
    assert len(ep) == 1
    assert abs(ep[0]["factor_value"] - 0.04) < 1e-12


def test_compute_final_factor_records_payout_ratio_falls_back_to_net_income_over_shares():
    atomic = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-31",
            "factor_name": "net_income",
            "factor_value": 500.0,
            "source_report_date": "2026-03-31",
            "publish_date": "2026-03-31",
            "source": "edgar",
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-31",
            "factor_name": "shares_outstanding",
            "factor_value": 100.0,
            "source_report_date": "2026-03-31",
            "publish_date": "2026-03-31",
            "source": "edgar",
        },
        {
            "symbol": "AAPL",
            "observation_date": "2025-09-30",
            "factor_name": "dividend_per_share",
            "factor_value": 1.0,
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-15",
            "factor_name": "dividend_per_share",
            "factor_value": 1.0,
        },
    ]
    out = factors.compute_final_factor_records(atomic, run_date="2026-03-31", backfill_years=1)
    payout = [
        r
        for r in out
        if r["factor_name"] == "payout_ratio" and r["observation_date"] == "2026-03-31"
    ]
    assert len(payout) == 1
    assert abs(payout[0]["factor_value"] - 0.4) < 1e-12


def test_compute_final_factor_records_ep_ratio_uses_mixed_source_fallback():
    atomic = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-31",
            "factor_name": "adjusted_close_price",
            "factor_value": 50.0,
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-31",
            "factor_name": "net_income",
            "factor_value": 200.0,
            "source_report_date": "2026-03-31",
            "publish_date": "2026-03-31",
            "source": "edgar",
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-31",
            "factor_name": "shares_outstanding",
            "factor_value": 100.0,
            "source_report_date": "2026-03-31",
            "publish_date": "2026-03-31",
            "source": "yfinance",
        },
    ]
    out = factors.compute_final_factor_records(atomic, run_date="2026-03-31", backfill_years=1)
    ep = [r for r in out if r["factor_name"] == "ep_ratio"]
    assert len(ep) == 1
    assert abs(ep[0]["factor_value"] - 0.04) < 1e-12


def test_compute_final_factor_records_generates_dividend_stability():
    quarter_dates = [
        "2022-03-31",
        "2022-06-30",
        "2022-09-30",
        "2022-12-31",
        "2023-03-31",
        "2023-06-30",
        "2023-09-30",
        "2023-12-31",
        "2024-03-31",
        "2024-06-30",
        "2024-09-30",
        "2024-12-31",
        "2025-03-31",
        "2025-06-30",
        "2025-09-30",
        "2025-12-31",
        "2026-03-31",
        "2026-06-30",
        "2026-09-30",
        "2026-12-31",
    ]
    atomic = [
        {
            "symbol": "AAPL",
            "observation_date": obs_date,
            "factor_name": "dividend_per_share",
            "factor_value": 0.25,
        }
        for obs_date in quarter_dates
    ]
    out = factors.compute_final_factor_records(atomic, run_date="2026-12-31", backfill_years=1)
    stability = [
        r
        for r in out
        if r["factor_name"] == "dividend_stability" and r["observation_date"] == "2026-12-31"
    ]
    assert len(stability) == 1
    assert 0.7 < stability[0]["factor_value"] <= 1.0
    assert stability[0]["publish_date"] == "2026-12-31"


def test_compute_final_factor_records_generates_publish_date_for_technical_factors():
    atomic = [
        {
            "symbol": "AAPL",
            "observation_date": f"2026-01-{day:02d}",
            "factor_name": "adjusted_close_price",
            "factor_value": float(100 + day),
        }
        for day in range(1, 32)
    ]
    out = factors.compute_final_factor_records(atomic, run_date="2026-01-31", backfill_years=1)
    by_key = {(r["factor_name"], r["observation_date"]): r for r in out}
    assert by_key[("momentum_1m", "2026-01-31")]["publish_date"] == "2026-01-31"
    assert by_key[("volatility_20d", "2026-01-31")]["publish_date"] == "2026-01-31"


def test_technical_factors_are_stable_across_run_window_front_edge():
    atomic = [
        {
            "symbol": "AAPL",
            "observation_date": f"2025-01-{day:02d}",
            "factor_name": "adjusted_close_price",
            "factor_value": float(100 + day),
        }
        for day in range(1, 32)
    ]
    atomic.extend(
        [
            {
                "symbol": "AAPL",
                "observation_date": f"2025-02-{day:02d}",
                "factor_name": "adjusted_close_price",
                "factor_value": float(131 + day),
            }
            for day in range(1, 29)
        ]
    )
    atomic.extend(
        [
            {
                "symbol": "AAPL",
                "observation_date": f"2025-03-{day:02d}",
                "factor_name": "adjusted_close_price",
                "factor_value": float(159 + day),
            }
            for day in range(1, 32)
        ]
    )

    out_early = factors.compute_final_factor_records(
        atomic, run_date="2026-01-31", backfill_years=1
    )
    out_late = factors.compute_final_factor_records(
        atomic, run_date="2026-02-28", backfill_years=1
    )

    early = {
        (r["factor_name"], r["observation_date"]): r
        for r in out_early
        if r["observation_date"] == "2025-03-10"
        and r["factor_name"] in {"momentum_1m", "volatility_20d"}
    }
    late = {
        (r["factor_name"], r["observation_date"]): r
        for r in out_late
        if r["observation_date"] == "2025-03-10"
        and r["factor_name"] in {"momentum_1m", "volatility_20d"}
    }

    assert set(early) == set(late) == {
        ("momentum_1m", "2025-03-10"),
        ("volatility_20d", "2025-03-10"),
    }
    assert early[("momentum_1m", "2025-03-10")]["factor_value"] == late[
        ("momentum_1m", "2025-03-10")
    ]["factor_value"]
    assert early[("volatility_20d", "2025-03-10")]["factor_value"] == late[
        ("volatility_20d", "2025-03-10")
    ]["factor_value"]


def test_compute_final_factor_records_generates_earnings_publication_flag():
    atomic = [
        {
            "symbol": "AAPL",
            "observation_date": "2025-12-31",
            "factor_name": "net_income",
            "factor_value": 100.0,
            "source_report_date": "2025-12-31",
            "publish_date": "2026-02-10",
        },
        {
            "symbol": "AAPL",
            "observation_date": "2025-12-31",
            "factor_name": "revenue",
            "factor_value": 500.0,
            "source_report_date": "2025-12-31",
            "publish_date": "2026-02-10",
        },
    ]
    out = factors.compute_final_factor_records(atomic, run_date="2026-03-31", backfill_years=1)
    flags = [
        row
        for row in out
        if row["factor_name"] == "earnings_publication_flag"
        and row["observation_date"] == "2026-02-10"
    ]
    assert len(flags) == 1
    assert flags[0]["factor_value"] == 1.0


def test_sentiment_rolling_factors_are_stable_across_run_window_front_edge():
    atomic = [
        {
            "symbol": "AAPL",
            "observation_date": "2025-02-10",
            "factor_name": "news_sentiment_daily",
            "factor_value": 0.3,
        },
        {
            "symbol": "AAPL",
            "observation_date": "2025-02-20",
            "factor_name": "news_sentiment_daily",
            "factor_value": -0.1,
        },
        {
            "symbol": "AAPL",
            "observation_date": "2025-02-10",
            "factor_name": "news_article_count_daily",
            "factor_value": 2.0,
        },
        {
            "symbol": "AAPL",
            "observation_date": "2025-02-20",
            "factor_name": "news_article_count_daily",
            "factor_value": 1.0,
        },
    ]

    out_early = factors.compute_final_factor_records(
        atomic, run_date="2026-01-31", backfill_years=1
    )
    out_late = factors.compute_final_factor_records(
        atomic, run_date="2026-02-28", backfill_years=1
    )

    early = {
        (r["factor_name"], r["observation_date"]): r
        for r in out_early
        if r["observation_date"] == "2025-03-05"
        and r["factor_name"]
        in {
            "sentiment_7d_avg",
            "sentiment_30d_avg",
            "article_count_7d",
            "article_count_30d",
            "sentiment_surprise",
        }
    }
    late = {
        (r["factor_name"], r["observation_date"]): r
        for r in out_late
        if r["observation_date"] == "2025-03-05"
        and r["factor_name"]
        in {
            "sentiment_7d_avg",
            "sentiment_30d_avg",
            "article_count_7d",
            "article_count_30d",
            "sentiment_surprise",
        }
    }

    assert set(early) == set(late)
    for key in sorted(early):
        assert early[key]["factor_value"] == late[key]["factor_value"]
        assert early[key]["publish_date"] == late[key]["publish_date"] == "2025-03-05"


def test_build_and_load_final_factors_calls_loader(monkeypatch):
    monkeypatch.setattr(
        factors,
        "_load_atomic_records_from_postgres",
        lambda **kwargs: [
            {
                "symbol": "AAPL",
                "observation_date": "2026-01-30",
                "factor_name": "adjusted_close_price",
                "factor_value": 100.0,
            },
            {
                "symbol": "AAPL",
                "observation_date": "2025-12-15",
                "factor_name": "dividend_per_share",
                "factor_value": 1.0,
            },
        ],
    )

    captured = {}

    def _fake_load(rows, dry_run=False, table_name="factor_observations"):
        captured["rows"] = rows
        captured["dry_run"] = dry_run
        captured["table_name"] = table_name
        return len(rows)

    monkeypatch.setattr(factors, "load_curated", _fake_load)

    out = factors.build_and_load_final_factors(
        run_date="2026-01-31",
        backfill_years=1,
        symbols=["AAPL"],
        dry_run=True,
    )
    assert out >= 1
    assert captured["dry_run"] is True
    assert any(r["factor_name"] == "dividend_yield" for r in captured["rows"])


def test_compute_final_factor_records_pb_ratio_uses_per_symbol_rolling_q99_with_enough_history():
    from datetime import date, timedelta

    atomic = []
    symbol = "S000"
    start = date(2026, 1, 1)
    dates = [
        start + timedelta(days=i) for i in range(90) if (start + timedelta(days=i)).weekday() < 5
    ]
    obs_date = dates[-1].isoformat()
    for d in dates:
        price = 1000.0 if d.isoformat() == obs_date else 1.0
        atomic.extend(
            [
                {
                    "symbol": symbol,
                    "observation_date": d.isoformat(),
                    "factor_name": "adjusted_close_price",
                    "factor_value": price,
                },
                {
                    "symbol": symbol,
                    "observation_date": d.isoformat(),
                    "factor_name": "shares_outstanding",
                    "factor_value": 100.0,
                    "source_report_date": d.isoformat(),
                    "source": "edgar",
                },
                {
                    "symbol": symbol,
                    "observation_date": d.isoformat(),
                    "factor_name": "total_shareholder_equity",
                    "factor_value": 100.0,
                    "source_report_date": d.isoformat(),
                    "source": "edgar",
                },
            ]
        )

    out = factors.compute_final_factor_records(atomic, run_date=obs_date, backfill_years=1)
    pb_rows = [
        r
        for r in out
        if r["factor_name"] == "pb_ratio"
        and r["observation_date"] == obs_date
        and r["symbol"] == symbol
    ]
    assert len(pb_rows) == 1
    outlier = pb_rows[0]
    # With enough per-symbol history, rolling q99 caps the outlier below raw 1000.
    assert outlier["factor_value"] < 1000.0
    assert outlier["factor_value"] > 100.0


def test_compute_final_factor_records_pb_ratio_falls_back_to_100_cap_for_small_per_symbol_sample():
    atomic = []
    obs_date = "2026-03-31"
    symbol = "T000"
    sample_dates = [f"2026-03-{d:02d}" for d in (22, 23, 24, 25, 26, 27, 28, 29, 30, 31)]
    for d in sample_dates:
        price = 1000.0 if d == obs_date else 1.0
        atomic.extend(
            [
                {
                    "symbol": symbol,
                    "observation_date": d,
                    "factor_name": "adjusted_close_price",
                    "factor_value": price,
                },
                {
                    "symbol": symbol,
                    "observation_date": d,
                    "factor_name": "shares_outstanding",
                    "factor_value": 100.0,
                    "source_report_date": d,
                    "source": "edgar",
                },
                {
                    "symbol": symbol,
                    "observation_date": d,
                    "factor_name": "total_shareholder_equity",
                    "factor_value": 100.0,
                    "source_report_date": d,
                    "source": "edgar",
                },
            ]
        )

    out = factors.compute_final_factor_records(atomic, run_date=obs_date, backfill_years=1)
    pb_rows = [
        r
        for r in out
        if r["factor_name"] == "pb_ratio"
        and r["observation_date"] == obs_date
        and r["symbol"] == symbol
    ]
    assert len(pb_rows) == 1
    outlier = pb_rows[0]
    assert outlier["factor_value"] == 100.0


def test_financial_staleness_logs_soft_and_hard_events(caplog):
    atomic = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-31",
            "factor_name": "adjusted_close_price",
            "factor_value": 50.0,
        },
        # stale but still usable for 2026-12-31 (age 275 days)
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-31",
            "factor_name": "shares_outstanding",
            "factor_value": 100.0,
            "source_report_date": "2026-03-31",
        },
        # expired for 2026-12-31 (age 366 days)
        {
            "symbol": "AAPL",
            "observation_date": "2025-12-30",
            "factor_name": "total_shareholder_equity",
            "factor_value": 1000.0,
            "source_report_date": "2025-12-30",
        },
    ]

    with caplog.at_level("WARNING"):
        out = factors.compute_final_factor_records(atomic, run_date="2026-12-31", backfill_years=1)

    # total_shareholder_equity expired => pb_ratio should be dropped for this date.
    pb_rows = [
        r for r in out if r["factor_name"] == "pb_ratio" and r["observation_date"] == "2026-12-31"
    ]
    assert pb_rows == []

    joined = "\n".join(caplog.messages)
    assert "quality_event_summary" in joined
    assert "stale_count=" in joined
    assert "expired_count=" in joined
    assert "stale_by_factor={'pb_ratio':" in joined
    assert "expired_by_factor={'pb_ratio':" in joined


def test_financial_staleness_verbose_event_logging(monkeypatch, caplog):
    atomic = [
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-31",
            "factor_name": "adjusted_close_price",
            "factor_value": 50.0,
        },
        {
            "symbol": "AAPL",
            "observation_date": "2026-03-31",
            "factor_name": "shares_outstanding",
            "factor_value": 100.0,
            "source_report_date": "2026-03-31",
        },
        {
            "symbol": "AAPL",
            "observation_date": "2025-12-30",
            "factor_name": "total_shareholder_equity",
            "factor_value": 1000.0,
            "source_report_date": "2025-12-30",
        },
    ]
    monkeypatch.setenv("QUALITY_VERBOSE_EVENTS", "1")
    with caplog.at_level("WARNING"):
        factors.compute_final_factor_records(atomic, run_date="2026-12-31", backfill_years=1)
    joined = "\n".join(caplog.messages)
    assert "flag_financial_stale=True" in joined
    assert "flag_data_expired=True" in joined


def test_pair_integrity_relaxed_logs_once_and_summarizes(caplog):
    factors._reset_pair_integrity_event_counts()

    with caplog.at_level("INFO"):
        factors._log_pair_integrity_relaxed(
            factor="ep_ratio",
            symbol="AAPL",
            left_metric="net_income",
            right_metric="shares_outstanding",
            cutoff=factors.date(2026, 4, 15),
            pair_mode="mixed_source_latest",
            left_source="edgar_xbrl",
            right_source="edgar_xbrl",
        )
        factors._log_pair_integrity_relaxed(
            factor="ep_ratio",
            symbol="AAPL",
            left_metric="net_income",
            right_metric="shares_outstanding",
            cutoff=factors.date(2026, 4, 16),
            pair_mode="mixed_source_latest",
            left_source="edgar_xbrl",
            right_source="edgar_xbrl",
        )
        factors._flush_pair_integrity_event_summary()

    relaxed_logs = [m for m in caplog.messages if "pair_integrity_relaxed=True" in m]
    assert len(relaxed_logs) == 1
    summary_logs = [m for m in caplog.messages if "pair_integrity_event_summary" in m]
    assert len(summary_logs) == 1
    assert "relaxed_total=2" in summary_logs[0]
    assert "'ep_ratio:mixed_source_latest': 2" in summary_logs[0]
