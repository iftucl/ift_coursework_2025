from __future__ import annotations

"""Initialize PostgreSQL schema/tables and seed company universe."""

import argparse
import os
import re
import subprocess  # nosec B404
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.utils.env import load_dotenv_if_exists  # noqa: E402

_SAFE_CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Initialize CW1 database by applying sql/init.sql and then seeding "
            "systematic_equity.company_static from teacher SQLite."
        )
    )
    parser.add_argument(
        "--container",
        default=os.getenv("POSTGRES_CONTAINER", "postgres_db_cw"),
        help="PostgreSQL container name (default: postgres_db_cw).",
    )
    parser.add_argument(
        "--db-user",
        default=os.getenv("POSTGRES_USER", "postgres"),
        help="PostgreSQL user for docker exec psql.",
    )
    parser.add_argument(
        "--db-name",
        default=os.getenv("POSTGRES_DB", "postgres"),
        help="PostgreSQL database for docker exec psql.",
    )
    parser.add_argument(
        "--sqlite-path",
        default=None,
        help="Optional override for source SQLite Equity.db path.",
    )
    return parser.parse_args()


def _validate_container_name(name: str) -> str:
    value = str(name or "").strip()
    if not value or not _SAFE_CONTAINER_RE.match(value):
        raise ValueError(f"Invalid container name: {name!r}")
    return value


def run_sql_init(container: str, db_user: str, db_name: str, init_sql_path: Path) -> None:
    if not init_sql_path.exists():
        raise FileNotFoundError(f"init.sql not found: {init_sql_path}")

    sql_bytes = init_sql_path.read_bytes()
    safe_container = _validate_container_name(container)
    cmd = [
        "docker",
        "exec",
        "-i",
        safe_container,
        "psql",
        "-U",
        db_user,
        "-d",
        db_name,
    ]
    # Safe: fixed argv + validated container name; shell not used.
    subprocess.run(
        cmd,
        input=sql_bytes,
        check=True,
    )  # nosec B603


def run_seed(sqlite_path: str | None, project_root: Path) -> None:
    seed_script = (project_root / "scripts" / "seed_universe_from_sqlite.py").resolve()
    cmd = [sys.executable, str(seed_script)]
    if sqlite_path:
        cmd.extend(["--sqlite-path", sqlite_path])
    env = os.environ.copy()
    existing = str(env.get("PYTHONPATH", "")).strip()
    root = str(project_root)
    env["PYTHONPATH"] = root if not existing else f"{root}{os.pathsep}{existing}"
    # Safe: fixed seed script path + explicit sqlite arg; shell not used.
    subprocess.run(
        cmd,
        check=True,
        cwd=str(project_root),
        env=env,
    )  # nosec B603


def main() -> int:
    project_root = PROJECT_ROOT
    # Ensure POSTGRES_* defaults can be sourced from local .env for subprocess calls.
    load_dotenv_if_exists(project_root / ".env")
    args = parse_args()
    init_sql_path = project_root / "sql" / "init.sql"

    run_sql_init(args.container, args.db_user, args.db_name, init_sql_path)
    run_seed(args.sqlite_path, project_root)
    print("DB init completed: schema/tables applied and universe seeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
