#!/usr/bin/env python3
"""Validate the Airflow container's shared runtime wiring."""

from __future__ import annotations

import importlib
import os
import socket
import sys
from typing import Iterable


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def _require_env(names: Iterable[str]) -> None:
    for name in names:
        if not os.environ.get(name):
            _fail(f"missing required env var: {name}")


def _require_import(module_name: str) -> None:
    try:
        importlib.import_module(module_name)
    except Exception as exc:  # pragma: no cover - runtime-only safeguard
        _fail(f"missing python dependency {module_name}: {exc}")


def _require_resolves(endpoint: str) -> None:
    host = endpoint.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].strip()
    if not host:
        _fail(f"unable to parse hostname from endpoint: {endpoint}")
    try:
        socket.gethostbyname(host)
    except OSError as exc:  # pragma: no cover - runtime-only safeguard
        _fail(f"hostname {host} is not resolvable: {exc}")


def main() -> int:
    _require_env(
        [
            "POSTGRES_HOST",
            "MONGO_HOST",
            "MINIO_ENDPOINT",
            "REDIS_HOST",
        ]
    )
    _require_import("minio")
    _require_resolves(os.environ["MINIO_ENDPOINT"])
    _require_resolves(os.environ["REDIS_HOST"])
    _require_resolves(os.environ["POSTGRES_HOST"])
    _require_resolves(os.environ["MONGO_HOST"])

    kafka_enabled = os.environ.get("KAFKA_ENABLED", "").strip().lower() == "true"
    if kafka_enabled:
        _require_env(["KAFKA_BOOTSTRAP_SERVERS"])
        _require_import("kafka")
        for endpoint in os.environ["KAFKA_BOOTSTRAP_SERVERS"].split(","):
            _require_resolves(endpoint.strip())

    print("airflow runtime environment healthy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
