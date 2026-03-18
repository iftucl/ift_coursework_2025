import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "init_db.py"
_SPEC = importlib.util.spec_from_file_location("cw1_init_db", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
init_db = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("cw1_init_db", init_db)
_SPEC.loader.exec_module(init_db)


class _Completed:
    def __init__(self, stdout: str = ""):
        self.stdout = stdout


def test_ensure_database_exists_skips_when_database_already_exists(monkeypatch):
    calls = []

    def _run(cmd, check, capture_output=False, text=False, **kwargs):  # noqa: ARG001
        calls.append(cmd)
        return _Completed(stdout="fift | postgres | UTF8\n")

    monkeypatch.setattr(init_db.subprocess, "run", _run)
    init_db.ensure_database_exists("postgres_db_cw", "postgres", "postgres", "fift")
    assert len(calls) == 1
    assert "createdb" not in calls[0]


def test_ensure_database_exists_creates_missing_database(monkeypatch):
    calls = []

    def _run(cmd, check, capture_output=False, text=False, **kwargs):  # noqa: ARG001
        calls.append(cmd)
        if "createdb" in cmd:
            return _Completed()
        return _Completed(stdout="")

    monkeypatch.setattr(init_db.subprocess, "run", _run)
    init_db.ensure_database_exists("postgres_db_cw", "postgres", "postgres", "fift")
    assert len(calls) == 2
    assert "createdb" in calls[1]
    assert calls[1][-1] == "fift"


def test_ensure_database_exists_tolerates_race_when_created_elsewhere(monkeypatch):
    calls = []

    def _run(cmd, check, capture_output=False, text=False, **kwargs):  # noqa: ARG001
        calls.append(cmd)
        if "createdb" in cmd:
            raise subprocess.CalledProcessError(returncode=1, cmd=cmd)
        if len(calls) >= 3:
            return _Completed(stdout="fift | postgres | UTF8\n")
        return _Completed(stdout="")

    monkeypatch.setattr(init_db.subprocess, "run", _run)
    init_db.ensure_database_exists("postgres_db_cw", "postgres", "postgres", "fift")
    assert len(calls) == 3
    assert "createdb" in calls[1]


def test_validate_db_name_rejects_invalid_names():
    with pytest.raises(ValueError, match="Invalid database name"):
        init_db._validate_db_name("bad-name")
