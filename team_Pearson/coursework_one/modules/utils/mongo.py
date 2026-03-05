from __future__ import annotations

"""Shared MongoDB config/connection helpers for scripts."""

import os
from pathlib import Path
from typing import Any

import yaml
from pymongo import MongoClient
from pymongo.collection import Collection


def load_mongo_cfg(config_path: str, project_root: Path) -> dict[str, Any]:
    """Load mongo config section from YAML config file."""
    cfg_path = Path(config_path)
    if not cfg_path.is_absolute():
        cfg_path = project_root / cfg_path
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return dict(cfg.get("mongo") or {})


def _read_env_or_cfg(env_key: str, cfg: dict[str, Any], cfg_key: str, default: str = "") -> str:
    raw = os.getenv(env_key, str(cfg.get(cfg_key, default) or default))
    return str(raw).strip()


def resolve_mongo_db(cli_mongo_db: str, mongo_cfg: dict[str, Any]) -> str:
    """Resolve Mongo DB with priority: CLI > env > config > default."""
    cli_value = str(cli_mongo_db or "").strip()
    if cli_value:
        return cli_value
    env_value = str(os.getenv("MONGO_DB", "")).strip()
    if env_value:
        return env_value
    cfg_value = str(mongo_cfg.get("database", "")).strip()
    if cfg_value:
        return cfg_value
    return "ift_cw"


def build_mongo_client(mongo_cfg: dict[str, Any]) -> MongoClient:
    """Construct MongoClient from env/config."""
    host = _read_env_or_cfg("MONGO_HOST", mongo_cfg, "host", "localhost")
    port = int(_read_env_or_cfg("MONGO_PORT", mongo_cfg, "port", "27019"))
    uri = os.getenv("MONGO_URI", "").strip()
    if uri:
        return MongoClient(uri, serverSelectionTimeoutMS=5000)
    return MongoClient(host=host, port=port, serverSelectionTimeoutMS=5000)


def build_mongo_collection(
    mongo_cfg: dict[str, Any], collection_name: str, mongo_db: str
) -> tuple[MongoClient, Collection]:
    """Return (client, collection) for explicit lifecycle management."""
    client = build_mongo_client(mongo_cfg)
    return client, client[mongo_db][collection_name]
