from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from team_Pearson.coursework_two.modules.reporting.report import (
    _build_report_header_payload,
    _default_output_root,
    _plot_nav_chart,
    build_backtest_report_artifacts,
    generate_backtest_report_from_config,
)


def _sample_report_inputs() -> dict:
    dates = pd.to_datetime(["2026-01-31", "2026-02-28", "2026-03-31"])
    return {
        "holdings": pd.DataFrame(
            {
                "rebalance_date": pd.to_datetime(["2026-01-31", "2026-01-31", "2026-02-28"]),
                "execution_date": pd.to_datetime(["2026-01-31", "2026-01-31", "2026-02-28"]),
                "symbol": ["AAPL", "MSFT", "NVDA"],
                "target_weight": [0.08, 0.07, 0.09],
                "executed_weight": [0.08, 0.07, 0.09],
                "composite_alpha": [1.2, 1.1, 1.4],
                "gics_sector": ["Information Technology"] * 3,
            }
        ),
        "performance": pd.DataFrame(
            {
                "execution_date": dates,
                "period_end_date": dates,
                "portfolio_nav": [1.00, 1.04, 1.09],
                "benchmark_nav": [1.00, 1.02, 1.05],
                "risk_free_return": [0.002, 0.002, 0.002],
                "turnover": [1.0, 0.22, 0.15],
                "requested_turnover": [1.0, 0.25, 0.15],
                "gross_turnover": [1.0, 0.44, 0.30],
                "gross_requested_turnover": [1.0, 0.50, 0.30],
                "transaction_cost": [0.0015, 0.00033, 0.00022],
                "net_return": [0.01, 0.03, 0.04],
                "regime": ["normal", "stress", "normal"],
                "unfilled_buy_weight": [0.0, 0.03, 0.0],
                "unfilled_sell_weight": [0.0, 0.01, 0.0],
                "liquidity_clipped": [False, True, False],
                "forward_filled_symbol_count": [0, 1, 2],
                "forward_fill_day_count": [0, 2, 5],
                "max_participation_used": [0.02, 0.05, 0.01],
            }
        ),
        "metrics": pd.DataFrame(
            {
                "metric_group": [
                    "return",
                    "return",
                    "return",
                    "risk",
                    "risk_adjusted",
                    "risk_adjusted",
                    "risk_adjusted",
                    "portfolio",
                    "portfolio",
                    "portfolio",
                    "portfolio",
                    "portfolio",
                ],
                "metric_name": [
                    "total_return",
                    "annualized_return",
                    "gross_annualized_return",
                    "max_drawdown",
                    "sharpe_ratio",
                    "mar_ratio",
                    "hit_rate_vs_benchmark_ticker",
                    "avg_monthly_turnover_one_way",
                    "avg_monthly_turnover_two_way",
                    "annualized_turnover_ratio_one_way",
                    "annualized_turnover_ratio",
                    "avg_monthly_turnover",
                ],
                "metric_value": [
                    0.09,
                    0.40,
                    0.44,
                    -0.03,
                    1.4,
                    1.1,
                    49.15,
                    45.6,
                    91.2,
                    547.2,
                    547.2,
                    45.6,
                ],
                "metric_unit": [
                    "%",
                    "%",
                    "%",
                    "%",
                    "x",
                    "x",
                    "%",
                    "%",
                    "%",
                    "%",
                    "%",
                    "%",
                ],
            }
        ),
        "relative_metrics": pd.DataFrame(
            {
                "versus_series": ["universe_ew", "universe_ew"],
                "metric_name": ["excess_return_annualized", "information_ratio"],
                "metric_value": [0.08, 0.7],
                "metric_unit": ["%", "x"],
            }
        ),
        "scorecard": pd.DataFrame(
            {
                "criterion_id": [1, 2],
                "criterion_name": ["Positive excess return", "Lower stress drawdown"],
                "passed": [True, True],
                "evidence": [{"metric": 0.08}, {"metric": -0.03}],
            }
        ),
        "benchmark_metrics": pd.DataFrame(
            {
                "series_name": [
                    "SPY",
                    "SPY",
                    "SPY",
                    "SPY",
                    "universe_ew",
                    "universe_ew",
                    "universe_ew",
                    "universe_ew",
                    "static_baseline",
                    "static_baseline",
                    "static_baseline",
                    "static_baseline",
                    "static_baseline",
                    "static_baseline",
                    "static_baseline",
                    "static_baseline",
                    "static_baseline",
                ],
                "metric_name": [
                    "annualized_return",
                    "max_drawdown",
                    "sharpe_ratio",
                    "mar_ratio",
                    "annualized_return",
                    "max_drawdown",
                    "mar_ratio",
                    "sharpe_ratio",
                    "annualized_return",
                    "max_drawdown",
                    "sortino_ratio",
                    "mar_ratio",
                    "avg_monthly_turnover_one_way",
                    "avg_monthly_turnover_two_way",
                    "annualized_turnover_ratio_one_way",
                    "avg_transaction_cost_bps",
                    "total_cost_drag",
                ],
                "metric_value": [
                    12.4,
                    8.2,
                    0.71,
                    1.51,
                    10.1,
                    9.4,
                    0.63,
                    1.07,
                    11.2,
                    7.8,
                    0.88,
                    1.44,
                    24.5,
                    49.0,
                    294.0,
                    7.5,
                    0.35,
                ],
                "metric_unit": [
                    "%",
                    "%",
                    "x",
                    "x",
                    "%",
                    "%",
                    "x",
                    "x",
                    "%",
                    "%",
                    "x",
                    "x",
                    "%",
                    "%",
                    "%",
                    "bps",
                    "%",
                ],
            }
        ),
        "benchmark_nav": pd.DataFrame(
            {
                "execution_date": list(dates) + list(dates),
                "period_end_date": list(dates) + list(dates),
                "series_name": ["universe_ew"] * 3 + ["static_baseline"] * 3,
                "nav": [1.0, 1.01, 1.03, 1.0, 1.015, 1.04],
                "period_return": [0.0, 0.01, 0.0198, 0.0, 0.015, 0.0246],
                "risk_free_return": [0.002] * 6,
            }
        ),
        "regime_attribution": pd.DataFrame(
            {
                "regime": ["normal", "stress"],
                "versus_series": ["static_baseline", "static_baseline"],
                "excess_ann_return": [0.05, 0.02],
                "strategy_sharpe": [1.3, 0.8],
                "hit_rate": [0.66, 0.50],
            }
        ),
        "covariance_contributions": pd.DataFrame(
            {
                "rebalance_date": pd.to_datetime(["2026-03-31", "2026-03-31", "2026-03-31"]),
                "period_end_date": pd.to_datetime(["2026-03-31", "2026-03-31", "2026-03-31"]),
                "series_name": ["strategy", "strategy", "strategy"],
                "dimension_type": ["sector", "sector", "sector"],
                "dimension_name": ["Technology", "Financials", "Health Care"],
                "risk_contribution_pct": [0.42, 0.31, 0.27],
            }
        ),
        "trade_blotter": pd.DataFrame(
            {
                "trade_date": pd.to_datetime(["2026-01-31", "2026-02-03", "2026-02-10"]),
                "execution_date": pd.to_datetime(["2026-01-31", "2026-02-03", "2026-02-10"]),
                "source_layer": [
                    "monthly_rebalance",
                    "intraday_overlay",
                    "intraday_overlay",
                ],
                "record_granularity": ["symbol", "symbol", "portfolio"],
                "action_type": [
                    "monthly_rebalance_execution",
                    "stock_stop_loss",
                    "weekly_target_rebalance",
                ],
                "symbol": ["AAPL", "NVDA", None],
                "trade_side": ["buy", "sell", "rebalance"],
                "weight_before": [0.0, 0.12, 0.95],
                "weight_after": [0.08, 0.0, 0.90],
                "requested_trade_weight": [0.08, 0.15, 0.18],
                "executed_trade_weight": [0.08, 0.12, 0.18],
                "unfilled_weight": [0.0, 0.03, 0.0],
                "liquidity_clipped": [False, True, False],
                "had_forward_fill": [False, True, False],
                "forward_fill_days": [0, 2, None],
                "adv_usd": [5_000_000.0, 2_000_000.0, None],
                "liquidity_capacity_weight": [0.08, 0.12, None],
                "participation_ratio": [0.016, 0.05, None],
                "transaction_cost": [0.0002, 0.0004, 0.0007],
                "reason_code": [
                    "scheduled_rebalance",
                    "stop_loss_barrier",
                    "weekly_drift_recentering",
                ],
            }
        ),
    }


def test_build_backtest_report_artifacts_writes_charts_and_markdown(tmp_path: Path):
    run_row = {
        "run_id": "run-123",
        "run_name": "cw2_bt_demo",
        "start_date": "2021-04-14",
        "end_date": "2026-04-14",
        "rebalance_freq": "monthly",
        "benchmark_ticker": "SPY",
        "transaction_cost_bps": 12.5,
        "model_version": "model-v2",
        "backtest_engine_version": "bt-v2",
        "config_snapshot": {
            "backtest": {
                "start_date": "2021-04-14",
                "end_date": "2026-04-14",
                "rebalance_frequency": "monthly",
                "benchmark_ticker": "SPY",
            }
        },
    }
    package = build_backtest_report_artifacts(
        report_dir=tmp_path,
        report_name="cw2_bt_demo_report",
        run_row=run_row,
        report_inputs=_sample_report_inputs(),
        config={
            "backtest": {
                "analysis": {
                    "primary_benchmark": "SPY",
                    "secondary_benchmark": "universe_ew",
                }
            },
            "governance": {"versions": {"reporting_version": "report-v2"}},
        },
        report_id="report-123",
        lineage_context={
            "snapshot_id": "snapshot-123",
            "portfolio_snapshot_id": 99,
            "portfolio_name": "cw2_core_equity",
            "requested_as_of_date": "2026-03-31",
            "feature_as_of_date": "2026-03-31",
            "portfolio_as_of_date": "2026-03-31",
            "source_table_row_counts": {"factor_snapshot_rows": 100},
            "latest_upstream_dates": {"factor_observation_date": "2026-03-31"},
            "lineage_window": {"snapshot_count": 3},
        },
    )

    summary = package["summary"]
    assert summary["report_name"] == "cw2_bt_demo_report"
    assert Path(summary["markdown_path"]).exists()
    assert Path(summary["json_path"]).exists()
    assert len(summary["chart_paths"]) >= 4
    markdown = Path(summary["markdown_path"]).read_text(encoding="utf-8")
    assert "CW2 Backtest Report" in markdown
    assert "Scorecard" in markdown
    assert "Execution Realism" in markdown
    assert "nav_vs_benchmarks.png" in markdown
    assert "trade_blotter.csv" in markdown
    assert "Trade Blotter Preview" in markdown
    assert "Transaction cost assumption (all-in): `12.5 bps`" in markdown
    assert "Benchmark Construction Notes" in markdown
    assert "period-aligned `us_treasury_3m` risk-free returns" in markdown
    assert "arithmetic annualized mean excess return" in markdown
    assert "covariance beta on raw strategy and benchmark returns" in markdown
    assert "net of configured trading costs" in markdown
    assert "Benchmark Execution Metrics" in markdown
    assert "| static_baseline | 24.50% | 49.00% | 294.00% | 7.5 | 0.35% |" in markdown
    assert "Average monthly turnover ratio (one-way): 45.60%" in markdown
    assert "Average monthly turnover ratio (two-way): 91.20%" in markdown
    assert "Annualized turnover ratio (one-way): 547.20%" in markdown
    assert "MAR ratio (full-period max drawdown): 1.100" in markdown
    assert "Hit rate vs benchmark ticker: 49.15%" in markdown
    assert "Benchmark Absolute Metrics" in markdown
    assert "| SPY |" in markdown
    assert "Average executed traded weight (two-way): 58.00%" in markdown
    assert "Gross annualized return: 0.44%" in markdown
    assert "0.09%" in markdown
    assert "Liquidity-clipped periods: `1`" in markdown
    assert "Forward-filled periods: `2`" in markdown
    assert "model-v2" in markdown
    assert summary["version_bundle"]["reporting_version"] == "report-v2"
    assert summary["transaction_cost_bps"] == 12.5
    assert summary["analysis_available"] is True
    assert summary["report_id"] == "report-123"
    assert summary["snapshot_id"] == "snapshot-123"
    assert summary["portfolio_snapshot_id"] == 99
    assert summary["config_hash"]
    assert summary["lineage_window"]["snapshot_count"] == 3
    assert summary["source_table_row_counts"]["factor_snapshot_rows"] == 100
    assert summary["latest_upstream_dates"]["factor_observation_date"] == "2026-03-31"
    assert summary["sample_rebalance_dates"] == ["2026-01-31", "2026-02-28"]
    assert len(summary["sample_holdings"]) == 3
    assert summary["trade_blotter_head_hash"]
    assert summary["trade_blotter_full_hash"]
    assert summary["holdings_head_hash"]
    assert summary["holdings_row_count"] == 3
    assert summary["scorecard_passed"] == 2
    assert summary["scorecard_total"] == 2
    assert summary["gross_annualized_return"] == 0.44
    assert summary["mar_ratio"] == 1.1
    assert summary["hit_rate_vs_benchmark_ticker"] == 49.15
    assert summary["avg_monthly_turnover_one_way"] == 45.6
    assert summary["avg_monthly_turnover_two_way"] == 91.2
    assert summary["benchmark_absolute_metrics"]["SPY"]["annualized_return"] == 12.4
    assert summary["benchmark_absolute_metrics"]["static_baseline"]["sortino_ratio"] == 0.88
    assert summary["benchmark_absolute_metrics"]["SPY"]["mar_ratio"] == 1.51
    assert (
        summary["benchmark_execution_metrics"]["static_baseline"]["avg_monthly_turnover_one_way"]
        == 24.5
    )
    assert (
        summary["benchmark_execution_metrics"]["static_baseline"]["avg_transaction_cost_bps"] == 7.5
    )
    assert (
        summary["benchmark_methodology"]["static_baseline"]["cost_treatment"]
        == "net_of_configured_trading_costs"
    )
    assert summary["risk_metric_conventions"]["sharpe_ratio"] == "us_treasury_3m_period_return"
    assert (
        summary["risk_metric_conventions"]["information_ratio"]
        == "arithmetic_annualized_mean_excess_return_divided_by_annualized_tracking_error"
    )
    assert (
        summary["risk_metric_conventions"]["beta_raw"]
        == "covariance_of_raw_strategy_and_benchmark_returns_divided_by_benchmark_return_variance"
    )
    assert summary["risk_free_series_name"] == "us_treasury_3m"
    assert summary["liquidity_clipped_periods"] == 1
    assert summary["liquidity_clipped_trade_rows"] == 1
    assert summary["forward_filled_periods"] == 2
    assert summary["forward_filled_symbol_total"] == 3
    assert summary["forward_fill_day_total"] == 7
    assert summary["forward_filled_trade_rows"] == 1
    assert summary["avg_turnover_shortfall"] == pytest.approx(1.0)
    assert Path(tmp_path / "trade_blotter.csv").exists()


def test_build_backtest_report_artifacts_marks_analysis_available_without_benchmark_nav(
    tmp_path: Path,
):
    run_row = {
        "run_id": "run-123",
        "run_name": "cw2_bt_demo",
        "start_date": "2021-04-14",
        "end_date": "2026-04-14",
        "rebalance_freq": "monthly",
        "benchmark_ticker": "SPY",
        "transaction_cost_bps": 12.5,
    }
    report_inputs = _sample_report_inputs()
    report_inputs["benchmark_nav"] = pd.DataFrame()

    package = build_backtest_report_artifacts(
        report_dir=tmp_path,
        report_name="cw2_bt_demo_report",
        run_row=run_row,
        report_inputs=report_inputs,
        config={
            "backtest": {
                "analysis": {
                    "primary_benchmark": "SPY",
                    "secondary_benchmark": "universe_ew",
                }
            }
        },
    )

    summary = package["summary"]
    assert summary["analysis_available"] is True


def test_build_backtest_report_artifacts_derives_benchmark_metrics_when_table_missing(
    tmp_path: Path,
):
    report_inputs = _sample_report_inputs()
    report_inputs["benchmark_metrics"] = pd.DataFrame()

    package = build_backtest_report_artifacts(
        report_dir=tmp_path,
        report_name="cw2_bt_demo_report",
        run_row={
            "run_id": "run-123",
            "run_name": "cw2_bt_demo",
            "start_date": "2021-04-14",
            "end_date": "2026-04-14",
            "rebalance_freq": "monthly",
            "benchmark_ticker": "SPY",
            "transaction_cost_bps": 12.5,
        },
        report_inputs=report_inputs,
        config={
            "backtest": {
                "analysis": {
                    "primary_benchmark": "SPY",
                    "secondary_benchmark": "universe_ew",
                }
            }
        },
    )

    summary = package["summary"]
    assert "universe_ew" in summary["benchmark_absolute_metrics"]
    assert summary["benchmark_absolute_metrics"]["universe_ew"]["max_drawdown"] is not None


def test_build_backtest_report_artifacts_relabels_scheduled_trades_by_frequency(
    tmp_path: Path,
):
    package = build_backtest_report_artifacts(
        report_dir=tmp_path,
        report_name="cw2_bt_demo_report",
        run_row={
            "run_id": "run-123",
            "run_name": "cw2_bt_demo",
            "start_date": "2021-04-14",
            "end_date": "2026-04-14",
            "rebalance_freq": "quarterly",
            "benchmark_ticker": "SPY",
            "transaction_cost_bps": 12.5,
        },
        report_inputs=_sample_report_inputs(),
        config={
            "backtest": {
                "analysis": {
                    "primary_benchmark": "SPY",
                    "secondary_benchmark": "universe_ew",
                }
            }
        },
    )

    summary = package["summary"]
    markdown = Path(summary["markdown_path"]).read_text(encoding="utf-8")
    trade_blotter_csv = Path(tmp_path / "trade_blotter.csv").read_text(encoding="utf-8")

    assert summary["scheduled_execution_row_count"] == 1
    assert "Scheduled execution rows: `1`" in markdown
    assert "Forward-filled blotter rows: `1`" in markdown
    assert "quarterly_rebalance" in markdown
    assert "quarterly_rebalance_execution" in markdown
    assert "monthly_rebalance" not in markdown
    assert "quarterly_rebalance" in trade_blotter_csv
    assert "quarterly_rebalance_execution" in trade_blotter_csv
    assert "monthly_rebalance" not in trade_blotter_csv


def test_plot_nav_chart_deduplicates_primary_benchmark_label(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    plot_labels: list[str | None] = []
    dates = pd.to_datetime(["2026-01-31", "2026-02-28", "2026-03-31"])
    performance_df = pd.DataFrame(
        {
            "period_end_date": dates,
            "portfolio_nav": [1.00, 1.04, 1.09],
            "benchmark_nav": [1.00, 1.02, 1.05],
        }
    )
    benchmark_nav_df = pd.DataFrame(
        {
            "period_end_date": list(dates) + list(dates) + list(dates),
            "series_name": ["SPY"] * 3 + ["universe_ew"] * 3 + ["static_baseline"] * 3,
            "nav": [1.0, 1.02, 1.05, 1.0, 1.01, 1.03, 1.0, 1.015, 1.04],
        }
    )

    from matplotlib.axes import Axes

    original_plot = Axes.plot

    def _recording_plot(self, *args, **kwargs):
        plot_labels.append(kwargs.get("label"))
        return original_plot(self, *args, **kwargs)

    monkeypatch.setattr(Axes, "plot", _recording_plot)

    _plot_nav_chart(
        performance_df=performance_df,
        benchmark_nav_df=benchmark_nav_df,
        run_row={"benchmark_ticker": "SPY"},
        output_path=tmp_path / "nav.png",
    )

    assert plot_labels.count("SPY") == 1
    assert "strategy" in plot_labels
    assert "universe_ew" in plot_labels
    assert "static_baseline" in plot_labels


def test_generate_backtest_report_from_config_upserts_registry(monkeypatch, tmp_path: Path):
    captured = {"report_header": None, "artifacts": None}
    quality = {}

    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.reporting.report._load_config",
        lambda path: {
            "backtest": {
                "analysis": {
                    "primary_benchmark": "SPY",
                    "secondary_benchmark": "universe_ew",
                }
            }
        },
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.reporting.report.ensure_reporting_schema",
        lambda engine: None,
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.reporting.report.ensure_backtest_schema",
        lambda engine: None,
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.reporting.report._load_run_row",
        lambda engine, run_id: {
            "run_id": run_id,
            "run_name": "cw2_bt_demo",
            "start_date": "2021-04-14",
            "end_date": "2026-04-14",
            "rebalance_freq": "monthly",
            "benchmark_ticker": "SPY",
            "transaction_cost_bps": 12.5,
        },
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.reporting.report._load_report_inputs",
        lambda engine, run_id: _sample_report_inputs(),
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.reporting.report._resolve_existing_report_id",
        lambda engine, run_id, report_name: None,
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.reporting.report._load_report_lineage_context",
        lambda engine, run_row: {},
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.reporting.report._upsert_report_header",
        lambda engine, **kwargs: captured.__setitem__("report_header", kwargs) or "report-123",
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.reporting.report._replace_report_artifacts",
        lambda engine, **kwargs: captured.__setitem__("artifacts", kwargs["artifacts"]),
    )
    monkeypatch.setattr(
        "team_Pearson.coursework_two.modules.reporting.report.record_quality_snapshot",
        lambda **kwargs: quality.update(kwargs),
    )

    result = generate_backtest_report_from_config(
        run_id="run-123",
        db_engine=object(),
        report_name="ops_report",
        output_dir=str(tmp_path),
    )

    assert result["report_id"] == "report-123"
    assert result["artifact_count"] >= 6
    assert captured["report_header"]["report_name"] == "ops_report"
    assert any(item["artifact_role"] == "chart" for item in captured["artifacts"])
    assert any(item["artifact_name"] == "trade_blotter" for item in captured["artifacts"])
    assert quality["dataset_name"] == "backtest_reports"
    assert quality["quality_report"]["passed"] is True
    assert quality["quality_report"]["artifact_count"] == result["artifact_count"]


def test_default_output_root_resolves_repo_relative_config_path():
    resolved = _default_output_root(
        {"reporting": {"output_dir": "team_Pearson/coursework_two/outputs/reports"}}
    )

    assert resolved == (
        Path(__file__).resolve().parents[3]
        / "team_Pearson"
        / "coursework_two"
        / "outputs"
        / "reports"
    )


def test_build_report_header_payload_includes_explicit_version_fields():
    payload = _build_report_header_payload(
        run_id="run-123",
        report_name="ops_report",
        output_dir="/tmp/report",
        run_row={
            "model_version": "model-v2",
            "factor_definition_version": "factor-v2",
            "covariance_method_version": "cov-v2",
            "risk_overlay_policy_version": "overlay-v2",
            "backtest_engine_version": "bt-v2",
        },
        config={"governance": {"versions": {"reporting_version": "report-v2"}}},
        summary={"report_name": "ops_report"},
    )

    assert payload["model_version"] == "model-v2"
    assert payload["backtest_engine_version"] == "bt-v2"
    assert payload["reporting_version"] == "report-v2"
