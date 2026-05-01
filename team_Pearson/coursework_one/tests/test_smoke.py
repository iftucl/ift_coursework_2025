import os
import subprocess
import sys


def _run_main(tmp_path, frequency: str):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cw_dir = os.path.abspath(os.path.join(base_dir, ".."))
    main_py = os.path.join(cw_dir, "Main.py")

    # 临时 config：把 run_log 写到 tmp_path，避免污染仓库日志文件
    cfg_path = tmp_path / "test_conf.yaml"
    run_log_path = tmp_path / "pipeline_runs.jsonl"
    cfg_path.write_text(
        "pipeline:\n"
        "  backfill_years: 1\n"
        "  company_limit: 2\n"
        "\n"
        "logging:\n"
        f"  run_log_path: {run_log_path.as_posix()}\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["CW1_TEST_MODE"] = "1"  # 关键：以后 extractor 要识别它并返回 mock
    env["PYTHONPATH"] = cw_dir + os.pathsep + env.get("PYTHONPATH", "")

    cmd = [
        sys.executable,
        main_py,
        "--config",
        str(cfg_path),
        "--run-date",
        "2026-02-14",
        "--frequency",
        frequency,
        "--backfill-years",
        "1",
        "--company-limit",
        "2",
        "--dry-run",
    ]
    return subprocess.run(
        cmd,
        cwd=cw_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_main_runs_daily_dry_run_smoke(tmp_path):
    res = _run_main(tmp_path, "daily")

    assert res.returncode == 0, f"stdout:\n{res.stdout}\n\nstderr:\n{res.stderr}"
    assert "run_log_written_to" in res.stdout
    assert "quality=" in res.stdout


def test_summarize_provider_usage_counts_only_total_debt_rows():
    import Main

    rows = [
        {"symbol": "AAPL", "factor_name": "adjusted_close_price", "source": "alpha_vantage"},
        {"symbol": "AAPL", "factor_name": "total_debt", "source": "alpha_vantage"},
        {"symbol": "MSFT", "factor_name": "total_debt", "source": "yfinance"},
    ]
    out = Main.summarize_provider_usage(rows)
    assert out == {"alpha_vantage": 1, "yfinance": 1}


def test_split_atomic_financial_records_routes_financial_atomic_rows():
    import Main

    rows = [
        {"symbol": "AAPL", "factor_name": "book_value", "source": "alpha_vantage"},
        {"symbol": "AAPL", "factor_name": "adjusted_close_price", "source": "alpha_vantage"},
    ]
    financial, remaining = Main.split_atomic_financial_records(rows)
    assert len(financial) == 1
    assert financial[0]["factor_name"] == "book_value"
    assert len(remaining) == 1
    assert remaining[0]["factor_name"] == "adjusted_close_price"
