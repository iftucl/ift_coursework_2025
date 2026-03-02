from __future__ import annotations

"""Minimal .env loader with safe key/value parsing (no shell execution)."""

import os
from pathlib import Path
from typing import Union

PathLike = Union[str, Path]


def load_dotenv_if_exists(path: PathLike, *, override: bool = False) -> None:
    """Load KEY=VALUE lines from .env file into os.environ.

    Rules:
    - ignore empty lines and comments
    - support optional ``export `` prefix
    - support quoted values ('...' or "...")
    - do not execute shell expressions
    - by default, do not override existing OS environment variables
    """
    env_path = Path(path)
    if not env_path.exists() or not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        if override or os.getenv(key) in (None, ""):
            os.environ[key] = value
