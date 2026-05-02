from __future__ import annotations

import json
from pathlib import Path

from team_Pearson.coursework_two.scripts.verify_reference_metrics import (
    _close_enough,
    _compare_value,
    _load_json,
    _lookup_path,
    main,
    verify_summary_against_reference,
)


def test_verify_summary_against_reference_supports_layered_contract():
    summary = {
        "start_date": "2021-04-20",
        "end_date": "2026-04-20",
        "rebalance_frequency": "quarterly",
        "primary_benchmark": "SPY",
        "benchmark_ticker": "SPY",
        "transaction_cost_bps": 15.0,
        "total_return": 74.115402,
        "annualized_return": 11.939622,
        "annualized_volatility": 15.816019,
        "sharpe_ratio": 0.582195,
        "max_drawdown": 17.130802,
        "information_ratio_vs_primary": 0.125923,
        "benchmark_total_return": 67.755749,
        "excess_return_vs_primary": 0.843966,
        "trade_blotter_row_count": 855,
        "latest_materialized_dates": {"performance_period_end_date": "2026-04-01"},
        "sample_rebalance_dates": ["2021-04-30", "2021-07-30"],
        "trade_blotter_head_hash": "abc123",
    }
    reference = {
        "reference_run": {
            "start_date": "2021-04-20",
            "end_date": "2026-04-20",
            "rebalance_frequency": "quarterly",
            "primary_benchmark": "SPY",
            "benchmark_ticker": "SPY",
            "transaction_cost_bps": 15.0,
            "expected_metrics": {
                "total_return": 74.115402,
                "annualized_return": 11.939622,
                "annualized_volatility": 15.816019,
                "sharpe_ratio": 0.582195,
                "max_drawdown": 17.130802,
                "information_ratio_vs_primary": 0.125923,
                "benchmark_total_return": 67.755749,
                "excess_return_vs_primary": 0.843966,
            },
            "expected_row_counts": {"trade_blotter_row_count": 855},
            "expected_latest_dates": {
                "latest_materialized_dates.performance_period_end_date": "2026-04-01"
            },
            "expected_sample_values": {"sample_rebalance_dates": ["2021-04-30", "2021-07-30"]},
            "expected_hashes": {"trade_blotter_head_hash": "abc123"},
        }
    }

    failures, layer_status = verify_summary_against_reference(
        summary=summary,
        reference=reference,
        tolerance=0.001,
    )

    assert failures == []
    assert all(layer_status.values())


def test_helper_functions_and_main_failure_path(tmp_path, monkeypatch, capsys):
    assert _close_enough(1.0, 1.0005, 0.001) is True
    assert _lookup_path({"a": {"b": 3}}, "a.b") == 3
    assert _lookup_path({"a": {}}, "a.missing") is None

    failures = []
    _compare_value(
        key_path="metric.path",
        actual_value="bad",
        expected_value=1.0,
        tolerance=0.001,
        failures=failures,
    )
    assert failures and "Numeric mismatch" in failures[0]

    summary_path = tmp_path / "summary.json"
    reference_path = tmp_path / "reference.json"
    summary_path.write_text(json.dumps({"start_date": "2026-01-01"}), encoding="utf-8")
    reference_path.write_text(
        json.dumps(
            {
                "reference_run": {
                    "start_date": "2026-01-02",
                    "end_date": "2026-04-20",
                    "rebalance_frequency": "quarterly",
                    "primary_benchmark": "SPY",
                    "benchmark_ticker": "SPY",
                    "transaction_cost_bps": 15.0,
                    "expected_metrics": {
                        "total_return": 0.0,
                        "annualized_return": 0.0,
                        "annualized_volatility": 0.0,
                        "sharpe_ratio": 0.0,
                        "max_drawdown": 0.0,
                        "information_ratio_vs_primary": 0.0,
                        "benchmark_total_return": 0.0,
                        "excess_return_vs_primary": 0.0,
                    },
                    "expected_row_counts": {},
                    "expected_latest_dates": {},
                    "expected_sample_values": {},
                    "expected_hashes": {},
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "argparse.ArgumentParser.parse_args",
        lambda self: type(
            "_Args",
            (),
            {
                "summary_path": str(summary_path),
                "reference_json": str(reference_path),
                "tolerance": 0.001,
            },
        )(),
    )

    rc = main()
    captured = capsys.readouterr()

    assert rc == 1
    assert "Reference metric verification failed:" in captured.out
    assert _load_json(Path(summary_path))["start_date"] == "2026-01-01"
