from __future__ import annotations

from pathlib import Path

from modules.utils import mongo as mongo_mod


def test_load_mongo_cfg_from_relative_path(tmp_path: Path):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "conf.yaml"
    cfg_path.write_text(
        "mongo:\n"
        "  host: mongodb\n"
        "  port: 27017\n"
        "  database: cw_db\n",
        encoding="utf-8",
    )

    out = mongo_mod.load_mongo_cfg("config/conf.yaml", tmp_path)
    assert out == {"host": "mongodb", "port": 27017, "database": "cw_db"}


def test_resolve_mongo_db_priority_cli_over_env_and_config(monkeypatch):
    monkeypatch.setenv("MONGO_DB", "env_db")
    out = mongo_mod.resolve_mongo_db("cli_db", {"database": "cfg_db"})
    assert out == "cli_db"


def test_resolve_mongo_db_priority_env_over_config(monkeypatch):
    monkeypatch.setenv("MONGO_DB", "env_db")
    out = mongo_mod.resolve_mongo_db("", {"database": "cfg_db"})
    assert out == "env_db"


def test_resolve_mongo_db_falls_back_to_config(monkeypatch):
    monkeypatch.delenv("MONGO_DB", raising=False)
    out = mongo_mod.resolve_mongo_db("", {"database": "cfg_db"})
    assert out == "cfg_db"


def test_resolve_mongo_db_defaults_to_ift_cw(monkeypatch):
    monkeypatch.delenv("MONGO_DB", raising=False)
    out = mongo_mod.resolve_mongo_db("", {})
    assert out == "ift_cw"


def test_build_mongo_client_prefers_uri(monkeypatch):
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _fake_mongo_client(*args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(mongo_mod, "MongoClient", _fake_mongo_client)
    monkeypatch.setenv("MONGO_URI", "mongodb://example:27017")
    client = mongo_mod.build_mongo_client({"host": "cfg-host", "port": 1111})

    assert client is not None
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ("mongodb://example:27017",)
    assert kwargs == {"serverSelectionTimeoutMS": 5000}


def test_build_mongo_client_uses_env_host_port_when_no_uri(monkeypatch):
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _fake_mongo_client(*args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(mongo_mod, "MongoClient", _fake_mongo_client)
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.setenv("MONGO_HOST", "env-host")
    monkeypatch.setenv("MONGO_PORT", "27099")
    client = mongo_mod.build_mongo_client({"host": "cfg-host", "port": 27017})

    assert client is not None
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ()
    assert kwargs == {"host": "env-host", "port": 27099, "serverSelectionTimeoutMS": 5000}


def test_build_mongo_client_uses_config_defaults_when_env_missing(monkeypatch):
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _fake_mongo_client(*args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(mongo_mod, "MongoClient", _fake_mongo_client)
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("MONGO_HOST", raising=False)
    monkeypatch.delenv("MONGO_PORT", raising=False)
    client = mongo_mod.build_mongo_client({"host": "cfg-host", "port": 27018})

    assert client is not None
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ()
    assert kwargs == {"host": "cfg-host", "port": 27018, "serverSelectionTimeoutMS": 5000}


def test_build_mongo_collection_returns_client_and_collection(monkeypatch):
    class _FakeDb:
        def __getitem__(self, collection_name: str):
            return ("COLL", collection_name)

    class _FakeClient:
        def __getitem__(self, db_name: str):
            assert db_name == "ift_cw"
            return _FakeDb()

    fake_client = _FakeClient()
    monkeypatch.setattr(mongo_mod, "build_mongo_client", lambda _cfg: fake_client)

    client, coll = mongo_mod.build_mongo_collection({}, "news_articles", "ift_cw")
    assert client is fake_client
    assert coll == ("COLL", "news_articles")
