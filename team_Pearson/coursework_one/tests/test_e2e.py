import os
import subprocess
import sys

import pytest


def _run_main(tmp_path, frequency: str):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cw_dir = os.path.abspath(os.path.join(base_dir, ".."))
    main_py = os.path.join(cw_dir, "Main.py")

    cfg_path = tmp_path / "test_conf.yaml"
    run_log_path = tmp_path / f"pipeline_runs_{frequency}.jsonl"
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
    env["CW1_TEST_MODE"] = "1"
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


@pytest.mark.parametrize("frequency", ["weekly", "monthly", "quarterly", "annual"])
def test_main_runs_dry_run_e2e(tmp_path, frequency):
    res = _run_main(tmp_path, frequency)

    assert res.returncode == 0, f"stdout:\n{res.stdout}\n\nstderr:\n{res.stderr}"
    assert "run_log_written_to" in res.stdout
    assert "quality=" in res.stdout
