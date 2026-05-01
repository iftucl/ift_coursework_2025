"""Unit tests for CW2 backtest summary metrics."""

import math
from datetime import date

from team_Pearson.coursework_two.modules.backtest.metrics import compute_backtest_metrics


def test_compute_backtest_metrics_scales_percentage_fields():
    records = [
        {
            "execution_date": date(2026, 1, 1),
            "period_end_date": date(2026, 1, 31),
            "gross_return": 0.02,
            "net_return": 0.018,
            "benchmark_return": 0.01,
            "risk_free_return": 0.002,
            "excess_return": 0.008,
            "portfolio_nav": 1.018,
            "benchmark_nav": 1.01,
            "turnover": 0.5,
            "gross_turnover": 1.0,
            "transaction_cost": 0.0015,
            "num_holdings": 25,
            "regime": "normal",
            "vix_level": 18.0,
        },
        {
            "execution_date": date(2026, 2, 1),
            "period_end_date": date(2026, 2, 28),
            "gross_return": -0.01,
            "net_return": -0.011,
            "benchmark_return": -0.005,
            "risk_free_return": 0.002,
            "excess_return": -0.006,
            "portfolio_nav": 1.006802,
            "benchmark_nav": 1.00495,
            "turnover": 0.1,
            "gross_turnover": 0.2,
            "transaction_cost": 0.0003,
            "num_holdings": 24,
            "regime": "normal",
            "vix_level": 19.5,
        },
    ]

    metrics = compute_backtest_metrics(records, initial_nav=1.0)
    lookup = {(m["metric_group"], m["metric_name"]): m for m in metrics}

    assert lookup[("return", "total_return")]["metric_unit"] == "%"
    assert math.isclose(
        lookup[("return", "total_return")]["metric_value"],
        0.6802,
        rel_tol=0,
        abs_tol=1e-4,
    )
    gross_ann = lookup[("return", "gross_annualized_return")]["metric_value"]
    net_ann = lookup[("return", "annualized_return")]["metric_value"]
    cost_drag = lookup[("portfolio", "total_cost_drag")]["metric_value"]
    avg_turnover = lookup[("portfolio", "avg_monthly_turnover")]["metric_value"]
    avg_turnover_one_way = lookup[("portfolio", "avg_monthly_turnover_one_way")]["metric_value"]
    annualized_turnover = lookup[("portfolio", "annualized_turnover_ratio")]["metric_value"]
    annualized_turnover_one_way = lookup[("portfolio", "annualized_turnover_ratio_one_way")][
        "metric_value"
    ]
    avg_gross_turnover = lookup[("portfolio", "avg_monthly_gross_turnover")]["metric_value"]
    avg_turnover_two_way = lookup[("portfolio", "avg_monthly_turnover_two_way")]["metric_value"]
    annualized_turnover_two_way = lookup[("portfolio", "annualized_turnover_ratio_two_way")][
        "metric_value"
    ]
    assert gross_ann > net_ann
    assert math.isclose(gross_ann - net_ann, cost_drag, rel_tol=0, abs_tol=1e-9)
    assert math.isclose(avg_turnover, 30.0, rel_tol=0, abs_tol=1e-9)
    assert math.isclose(avg_turnover_one_way, 30.0, rel_tol=0, abs_tol=1e-9)
    assert math.isclose(annualized_turnover, 360.0, rel_tol=0, abs_tol=1e-9)
    assert math.isclose(annualized_turnover_one_way, 360.0, rel_tol=0, abs_tol=1e-9)
    assert math.isclose(avg_gross_turnover, 60.0, rel_tol=0, abs_tol=1e-9)
    assert math.isclose(avg_turnover_two_way, 60.0, rel_tol=0, abs_tol=1e-9)
    assert math.isclose(annualized_turnover_two_way, 720.0, rel_tol=0, abs_tol=1e-9)
    assert lookup[("risk", "max_drawdown")]["metric_value"] >= 0
    assert lookup[("risk", "beta_raw")]["metric_unit"] == "-"
    assert lookup[("risk_adjusted", "mar_ratio")]["metric_unit"] == "x"
    assert ("risk_adjusted", "calmar_ratio") not in lookup
    assert lookup[("risk_adjusted", "hit_rate_vs_benchmark_ticker")]["metric_unit"] == "%"
    monthly_net_excess_over_rf = [0.018 - 0.002, -0.011 - 0.002]
    expected_sharpe = (sum(monthly_net_excess_over_rf) / len(monthly_net_excess_over_rf) * 12.0) / (
        math.sqrt(12.0)
        * (
            sum(
                (x - (sum(monthly_net_excess_over_rf) / len(monthly_net_excess_over_rf))) ** 2
                for x in monthly_net_excess_over_rf
            )
            / (len(monthly_net_excess_over_rf) - 1)
        )
        ** 0.5
    )
    assert math.isclose(
        lookup[("risk_adjusted", "sharpe_ratio")]["metric_value"],
        expected_sharpe,
        rel_tol=0,
        abs_tol=1e-9,
    )
    monthly_excess = [0.018 - 0.01, -0.011 - (-0.005)]
    expected_ir = (sum(monthly_excess) / len(monthly_excess) * 12.0) / (
        math.sqrt(12.0)
        * (
            sum((x - (sum(monthly_excess) / len(monthly_excess))) ** 2 for x in monthly_excess)
            / (len(monthly_excess) - 1)
        )
        ** 0.5
    )
    assert math.isclose(
        lookup[("risk_adjusted", "information_ratio")]["metric_value"],
        expected_ir,
        rel_tol=0,
        abs_tol=1e-9,
    )
    assert lookup[("portfolio", "avg_transaction_cost_bps")]["metric_unit"] == "bps"
