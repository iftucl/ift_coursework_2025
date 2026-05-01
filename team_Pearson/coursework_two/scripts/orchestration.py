from __future__ import annotations

"""Shared helpers for Airflow and scheduler-safe CW2 orchestration scripts."""

import json
import sys
from calendar import monthrange
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from sqlalchemy import text
from sqlalchemy.engine import Engine

REPO_ROOT = Path(__file__).resolve().parents[3]
CW1_ROOT = REPO_ROOT / "team_Pearson" / "coursework_one"
CW2_ROOT = REPO_ROOT / "team_Pearson" / "coursework_two"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from team_Pearson.coursework_one.modules.db.db_connection import get_db_engine  # noqa: E402
from team_Pearson.coursework_one.modules.db.universe import get_company_universe  # noqa: E402
from team_Pearson.coursework_one.modules.utils.env import load_dotenv_if_exists  # noqa: E402
from team_Pearson.coursework_two.modules.backtest.data_loader import (  # noqa: E402
    get_month_end_trading_days,
    load_trading_calendar,
)

_SCHEMA = "systematic_equity"


def default_cw1_config() -> str:
    return str(CW1_ROOT / "config" / "conf.yaml")


def default_cw2_config() -> str:
    return str(CW2_ROOT / "config" / "conf.yaml")


def load_env_layers() -> None:
    load_dotenv_if_exists(CW1_ROOT / ".env")
    load_dotenv_if_exists(CW2_ROOT / ".env", override=True)


def load_yaml(path: str) -> Dict[str, Any]:
    resolved = Path(path).resolve()
    default_cw2 = (CW2_ROOT / "config" / "conf.yaml").resolve()
    if resolved == default_cw2:
        from team_Pearson.coursework_two.modules.utils.config_validation import load_cw2_config

        return load_cw2_config(str(resolved))
    with resolved.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def coerce_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text_value = str(value).strip()
    if not text_value or text_value.lower() in {"none", "null", "auto"}:
        return None
    return text_value


def coerce_optional_int(value: Any) -> Optional[int]:
    text_value = coerce_optional_str(value)
    if text_value is None:
        return None
    return int(text_value)


def coerce_optional_float(value: Any) -> Optional[float]:
    text_value = coerce_optional_str(value)
    if text_value is None:
        return None
    return float(text_value)


def coerce_bool(value: Any, *, default: bool = False) -> bool:
    text_value = coerce_optional_str(value)
    if text_value is None:
        return default
    return text_value.lower() in {"1", "true", "yes", "y", "on"}


def resolve_company_limit(company_limit: Optional[int], cw1_config_path: str) -> Optional[int]:
    if company_limit is not None:
        return company_limit
    cfg = load_yaml(cw1_config_path)
    return (cfg.get("pipeline") or {}).get("company_limit")


def resolve_country_allowlist(cw1_config_path: str) -> Optional[object]:
    cfg = load_yaml(cw1_config_path)
    return (cfg.get("universe") or {}).get("country_allowlist")


def resolve_benchmark_ticker(cw2_config_path: str) -> str:
    cfg = load_yaml(cw2_config_path)
    bt_cfg = cfg.get("backtest") or {}
    return str(bt_cfg.get("benchmark_ticker") or "SPY")


def resolve_rebalance_frequency(cw2_config_path: str) -> str:
    cfg = load_yaml(cw2_config_path)
    bt_cfg = cfg.get("backtest") or {}
    portfolio_cfg = cfg.get("portfolio_construction") or {}
    value = str(
        bt_cfg.get("rebalance_frequency")
        or portfolio_cfg.get("target_generation_frequency")
        or "monthly"
    ).strip()
    lowered = value.lower()
    if lowered in {"monthly", "quarterly", "semiannual", "annual"}:
        return lowered
    return "monthly"


def month_end_trading_days(
    *,
    start_date: date,
    end_date: date,
    cw2_config_path: str,
    db_engine: Engine | None = None,
) -> List[date]:
    """Return month-end trading days used as the stored CW2 snapshot anchors.

    These anchors remain month-end even when the active portfolio target refresh
    cadence is less frequent. In those cases, off-cycle month-end snapshots may
    carry forward the previous target set instead of rebuilding a fresh one.
    """
    load_env_layers()
    engine = db_engine or get_db_engine()
    benchmark_ticker = resolve_benchmark_ticker(cw2_config_path)
    trading_days = load_trading_calendar(
        engine,
        start_date,
        end_date,
        benchmark_ticker=benchmark_ticker,
    )
    return get_month_end_trading_days(trading_days)


def scheduled_rebalance_trading_days(
    *,
    start_date: date,
    end_date: date,
    cw2_config_path: str,
    db_engine: Engine | None = None,
    include_first: bool = False,
) -> List[date]:
    """Return configured rebalance anchors derived from month-end trading days."""

    anchors = month_end_trading_days(
        start_date=start_date,
        end_date=end_date,
        cw2_config_path=cw2_config_path,
        db_engine=db_engine,
    )
    frequency = resolve_rebalance_frequency(cw2_config_path)
    if frequency == "monthly":
        return anchors

    allowed_months = {
        "quarterly": {3, 6, 9, 12},
        "semiannual": {6, 12},
        "annual": {12},
    }.get(frequency, set())

    scheduled: List[date] = []
    for idx, anchor in enumerate(anchors):
        if include_first and idx == 0:
            scheduled.append(anchor)
            continue
        if anchor.month in allowed_months:
            scheduled.append(anchor)
    return scheduled


def is_month_end_trading_day(
    *,
    run_date: date,
    cw2_config_path: str,
    db_engine: Engine | None = None,
) -> bool:
    month_last_day = monthrange(run_date.year, run_date.month)[1]
    month_start = run_date.replace(day=1)
    month_end = run_date.replace(day=month_last_day)
    return run_date in month_end_trading_days(
        start_date=month_start,
        end_date=month_end,
        cw2_config_path=cw2_config_path,
        db_engine=db_engine,
    )


def is_rebalance_trading_day(
    *,
    run_date: date,
    cw2_config_path: str,
    db_engine: Engine | None = None,
) -> bool:
    month_last_day = monthrange(run_date.year, run_date.month)[1]
    month_start = run_date.replace(day=1)
    month_end = run_date.replace(day=month_last_day)
    return run_date in scheduled_rebalance_trading_days(
        start_date=month_start,
        end_date=month_end,
        cw2_config_path=cw2_config_path,
        db_engine=db_engine,
    )


def load_scheduler_symbols(
    *,
    company_limit: Optional[int],
    cw1_config_path: str,
    as_of_date: Optional[object] = None,
) -> List[str]:
    load_env_layers()
    resolved_limit = resolve_company_limit(company_limit, cw1_config_path)
    allowlist = resolve_country_allowlist(cw1_config_path)
    return get_company_universe(
        resolved_limit,
        country_allowlist=allowlist,
        as_of_date=as_of_date,
    )


def existing_portfolio_target_count(
    *,
    as_of_date: date,
    portfolio_name: str,
    db_engine: Engine | None = None,
) -> int:
    load_env_layers()
    engine = db_engine or get_db_engine()
    sql = text(f"""
        SELECT COUNT(1)
        FROM {_SCHEMA}.portfolio_target_positions
        WHERE as_of_date = :as_of_date
          AND portfolio_name = :portfolio_name
        """)
    with engine.connect() as conn:
        return int(
            conn.execute(
                sql,
                {"as_of_date": as_of_date, "portfolio_name": portfolio_name},
            ).scalar_one()
        )


def print_json(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
