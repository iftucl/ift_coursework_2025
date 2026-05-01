from __future__ import annotations

"""Structured extractor (Source A).

This module fetches market/fundamental data for symbols, persists raw payloads
to MinIO, and returns records aligned to the pipeline's curated schema.
"""

import json
import logging
import math
import os
import re
import time
from datetime import datetime, timedelta
from io import BytesIO
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import pandas as pd
import requests
import yaml

from .symbol_filter import filter_symbols

logger = logging.getLogger(__name__)
ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"
_ALPHA_KEY_PLACEHOLDERS = {
    "",
    "YOUR_KEY",
    "YOUR_API_KEY_HERE",
    "ALPHA_VANTAGE_API_KEY",
    "REPLACE_WITH_YOUR_KEY",
}
_SOURCE_A_RAW_SCHEMA_VERSION = "v5"
_SOURCE_A_PROVIDER_PAYLOAD_VERSION_DEFAULTS = {
    "alpha_vantage": "time_series_daily_adjusted_v1",
    "yfinance": "history_v1",
}
_SOURCE_A_QUARTERLY_METRIC_KEYS = (
    "total_debt",
    "total_shareholder_equity",
    "book_value",
    "shares_outstanding",
    "enterprise_ebitda",
    "enterprise_revenue",
)
_SOURCE_A_QUARTERLY_PROVENANCE_KEYS = (
    "value_source_by_metric",
    "publish_date_by_metric",
    "publish_date_source_by_metric",
    "provider_values_by_metric",
)
_SOURCE_A_EDGAR_RAW_PUBLISH_DATE_MAP = {
    "total_debt": "total_debt",
    "stockholders_equity": "total_shareholder_equity",
    "shares_outstanding": "shares_outstanding",
    "ebitda": "enterprise_ebitda",
    "total_revenue": "enterprise_revenue",
}


def _json_default(obj: Any) -> Any:
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def _coerce_iso_date_text(value: Any) -> str:
    """Normalize date-like values to ``YYYY-MM-DD`` text."""
    if hasattr(value, "date") and callable(getattr(value, "date", None)):
        try:
            return value.date().isoformat()
        except (AttributeError, TypeError, ValueError) as exc:
            logger.debug("source_a: date() coercion failed for %r: %s", value, exc)
    if hasattr(value, "isoformat"):
        try:
            rendered = value.isoformat()
            return str(rendered)[:10]
        except (AttributeError, TypeError, ValueError) as exc:
            logger.debug("source_a: isoformat() coercion failed for %r: %s", value, exc)

    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return raw[:10]
    if len(raw) >= 8 and raw[:8].isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return ""


def _coerce_finite_float(value: Any) -> Optional[float]:
    """Return finite float or ``None`` for invalid numerics."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _resolve_source_a_provider_payload_version(provider: str) -> str:
    """Resolve Source A provider payload version for raw archives."""
    return _SOURCE_A_PROVIDER_PAYLOAD_VERSION_DEFAULTS.get(
        str(provider or "").strip().lower(), "unknown"
    )


def _normalize_source_a_history_rows(rows: Any) -> tuple[List[Dict[str, Any]], List[str]]:
    """Normalize raw Source A history rows into a stable replay schema."""
    if rows in (None, ""):
        return [], []
    if not isinstance(rows, list):
        return [], ["history_not_list"]

    normalized: List[Dict[str, Any]] = []
    issues: List[str] = []
    for row in rows:
        if not isinstance(row, dict):
            issues.append("history_row_not_dict")
            continue
        observation_date = _coerce_iso_date_text(
            row.get("observation_date") or row.get("Date") or row.get("date")
        )
        if not observation_date:
            issues.append("history_missing_observation_date")
            continue
        normalized.append(
            {
                "observation_date": observation_date,
                "Open": _coerce_finite_float(row.get("Open")),
                "High": _coerce_finite_float(row.get("High")),
                "Low": _coerce_finite_float(row.get("Low")),
                "Close": _coerce_finite_float(row.get("Close")),
                "Dividends": _coerce_finite_float(row.get("Dividends")),
                "Volume": _coerce_finite_float(row.get("Volume")),
            }
        )
    return normalized, issues


def _normalize_publish_date_by_metric(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: Dict[str, str] = {}
    for key, raw_date in value.items():
        metric_key = str(key or "").strip()
        publish_date = _coerce_iso_date_text(raw_date)
        if metric_key and publish_date:
            normalized[metric_key] = publish_date
    return normalized


def _normalize_text_map(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: Dict[str, str] = {}
    for key, raw_text in value.items():
        metric_key = str(key or "").strip()
        text_value = str(raw_text or "").strip()
        if metric_key and text_value:
            normalized[metric_key] = text_value
    return normalized


def _normalize_provider_values_by_metric(value: Any) -> Dict[str, Dict[str, Dict[str, Any]]]:
    if not isinstance(value, dict):
        return {}
    normalized: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for metric_key, raw_provider_map in value.items():
        metric_name = str(metric_key or "").strip()
        if not metric_name or not isinstance(raw_provider_map, dict):
            continue
        normalized_provider_map: Dict[str, Dict[str, Any]] = {}
        for provider_name, raw_payload in raw_provider_map.items():
            provider = str(provider_name or "").strip()
            if not provider:
                continue
            payload = raw_payload if isinstance(raw_payload, dict) else {"value": raw_payload}
            metric_value = _coerce_finite_float(payload.get("value"))
            report_date = _coerce_iso_date_text(payload.get("report_date"))
            if metric_value is None and not report_date:
                continue
            provider_payload: Dict[str, Any] = {"value": metric_value}
            if report_date:
                provider_payload["report_date"] = report_date
            normalized_provider_map[provider] = provider_payload
        if normalized_provider_map:
            normalized[metric_name] = normalized_provider_map
    return normalized


def _normalize_source_a_quarterly_fundamentals(
    rows: Any,
) -> tuple[List[Dict[str, Any]], List[str]]:
    if rows in (None, ""):
        return [], []
    if not isinstance(rows, list):
        return [], ["quarterly_fundamentals_not_list"]

    normalized: List[Dict[str, Any]] = []
    issues: List[str] = []
    for row in rows:
        if not isinstance(row, dict):
            issues.append("quarterly_fundamental_row_not_dict")
            continue
        report_date = _coerce_iso_date_text(row.get("report_date"))
        if not report_date:
            issues.append("quarterly_fundamental_missing_report_date")
            continue

        normalized_row = dict(row)
        normalized_row["report_date"] = report_date
        for key in _SOURCE_A_QUARTERLY_METRIC_KEYS:
            if key in normalized_row:
                normalized_row[key] = _coerce_finite_float(normalized_row.get(key))
        if "publish_date" in normalized_row:
            normalized_row["publish_date"] = (
                _coerce_iso_date_text(normalized_row.get("publish_date")) or None
            )
        if "available_date" in normalized_row:
            normalized_row["available_date"] = (
                _coerce_iso_date_text(normalized_row.get("available_date")) or None
            )
        publish_date_by_metric = _normalize_publish_date_by_metric(
            normalized_row.get("publish_date_by_metric")
        )
        if publish_date_by_metric:
            normalized_row["publish_date_by_metric"] = publish_date_by_metric
        elif "publish_date_by_metric" in normalized_row:
            normalized_row.pop("publish_date_by_metric", None)
        value_source_by_metric = _normalize_text_map(normalized_row.get("value_source_by_metric"))
        if value_source_by_metric:
            normalized_row["value_source_by_metric"] = value_source_by_metric
        elif "value_source_by_metric" in normalized_row:
            normalized_row.pop("value_source_by_metric", None)
        publish_date_source_by_metric = _normalize_text_map(
            normalized_row.get("publish_date_source_by_metric")
        )
        if publish_date_source_by_metric:
            normalized_row["publish_date_source_by_metric"] = publish_date_source_by_metric
        elif "publish_date_source_by_metric" in normalized_row:
            normalized_row.pop("publish_date_source_by_metric", None)
        provider_values_by_metric = _normalize_provider_values_by_metric(
            normalized_row.get("provider_values_by_metric")
        )
        if provider_values_by_metric:
            normalized_row["provider_values_by_metric"] = provider_values_by_metric
        elif "provider_values_by_metric" in normalized_row:
            normalized_row.pop("provider_values_by_metric", None)
        normalized.append(normalized_row)

    normalized.sort(key=lambda x: str(x.get("report_date") or ""))
    return normalized, issues


def _normalize_source_a_payload(
    payload: Dict[str, Any], *, symbol: str, run_date: str
) -> Dict[str, Any]:
    """Normalize Source A raw payload before archive/replay."""
    raw = dict(payload or {})
    provider = str(raw.get("source_used") or raw.get("provider") or "").strip().lower()
    normalized_history, history_issues = _normalize_source_a_history_rows(raw.get("history"))
    validation_errors: List[str] = list(history_issues)

    fundamentals = raw.get("fundamentals")
    if fundamentals is None:
        fundamentals = {}
    elif not isinstance(fundamentals, dict):
        validation_errors.append("fundamentals_not_dict")
        fundamentals = {}
    else:
        fundamentals = dict(fundamentals)

    normalized_quarterly, quarterly_issues = _normalize_source_a_quarterly_fundamentals(
        fundamentals.get("quarterly_fundamentals")
    )
    validation_errors.extend(quarterly_issues)
    if normalized_quarterly or "quarterly_fundamentals" in fundamentals:
        fundamentals["quarterly_fundamentals"] = normalized_quarterly
    if "report_date" in fundamentals:
        fundamentals["report_date"] = _coerce_iso_date_text(fundamentals.get("report_date")) or None
    if "publish_date" in fundamentals:
        fundamentals["publish_date"] = _coerce_iso_date_text(fundamentals.get("publish_date")) or None
    if "available_date" in fundamentals:
        fundamentals["available_date"] = _coerce_iso_date_text(
            fundamentals.get("available_date")
        ) or None
    publish_date_by_metric = _normalize_publish_date_by_metric(
        fundamentals.get("publish_date_by_metric")
    )
    if publish_date_by_metric:
        fundamentals["publish_date_by_metric"] = publish_date_by_metric
    elif "publish_date_by_metric" in fundamentals:
        fundamentals.pop("publish_date_by_metric", None)
    value_source_by_metric = _normalize_text_map(fundamentals.get("value_source_by_metric"))
    if value_source_by_metric:
        fundamentals["value_source_by_metric"] = value_source_by_metric
    elif "value_source_by_metric" in fundamentals:
        fundamentals.pop("value_source_by_metric", None)
    publish_date_source_by_metric = _normalize_text_map(
        fundamentals.get("publish_date_source_by_metric")
    )
    if publish_date_source_by_metric:
        fundamentals["publish_date_source_by_metric"] = publish_date_source_by_metric
    elif "publish_date_source_by_metric" in fundamentals:
        fundamentals.pop("publish_date_source_by_metric", None)
    provider_values_by_metric = _normalize_provider_values_by_metric(
        fundamentals.get("provider_values_by_metric")
    )
    if provider_values_by_metric:
        fundamentals["provider_values_by_metric"] = provider_values_by_metric
    elif "provider_values_by_metric" in fundamentals:
        fundamentals.pop("provider_values_by_metric", None)

    payload_symbol = str(raw.get("symbol") or symbol).strip().upper()
    if not payload_symbol:
        validation_errors.append("missing_symbol")
        payload_symbol = str(symbol or "").strip().upper()

    payload_run_date = (
        _coerce_iso_date_text(raw.get("run_date") or run_date) or str(run_date).strip()
    )
    if not payload_run_date:
        validation_errors.append("missing_run_date")

    rows = raw.get("rows")
    try:
        declared_rows = int(rows) if rows not in (None, "") else len(normalized_history)
    except (TypeError, ValueError):
        declared_rows = len(normalized_history)
        validation_errors.append("rows_not_int")

    if declared_rows != len(normalized_history):
        validation_errors.append("rows_mismatch")
        declared_rows = len(normalized_history)

    return {
        "symbol": payload_symbol,
        "run_date": payload_run_date,
        "as_of_date": payload_run_date,
        "rows": declared_rows,
        "history": normalized_history,
        "total_debt": _coerce_finite_float(raw.get("total_debt")),
        "fundamentals": fundamentals,
        "source_used": provider or str(raw.get("source_used") or "").strip() or None,
        "normalized_schema_version": _SOURCE_A_RAW_SCHEMA_VERSION,
        "provider_payload_version": _resolve_source_a_provider_payload_version(provider),
        "schema_validation_status": "valid" if not validation_errors else "warning",
        "schema_validation_errors": sorted(set(validation_errors)),
    }


def load_config(config_path: str = "config/conf.yaml") -> Dict[str, Any]:
    """Load YAML configuration from disk.

    Parameters
    ----------
    config_path:
        Path to YAML config file.

    Returns
    -------
    dict[str, Any]
        Parsed config dictionary. Returns an empty dict when file is missing.
    """
    if not os.path.exists(config_path):
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _download_price_history(symbol: str, years_back: int, max_retries: int = 3):
    """Download price history from yfinance (primary free provider)."""
    import yfinance as yf

    period = f"{max(1, int(years_back))}y"
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            ticker = yf.Ticker(symbol)
            history = ticker.history(period=period, auto_adjust=True)
            if history is None or history.empty:
                raise ValueError(f"No history returned for symbol={symbol}")
            return ticker, history
        except Exception as exc:  # pragma: no cover - network/runtime dependent
            last_error = exc
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
            else:
                raise RuntimeError(f"source_a history download failed for {symbol}: {exc}") from exc

    raise RuntimeError(f"source_a history download failed for {symbol}: {last_error}")


def _apply_history_window(
    history: pd.DataFrame,
    run_date: str,
    backfill_years: int,
    *,
    prior_rows: int = 0,
) -> pd.DataFrame:
    """Trim history to rolling-month window ending at run_date.

    Optionally retain a small number of pre-window rows so boundary metrics such as
    ``daily_return`` can reference the immediately preceding trading day.
    """
    if history is None or history.empty:
        return history

    frame = history.sort_index().copy()
    idx = pd.to_datetime(frame.index, errors="coerce")
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert(None)

    end_ts = pd.Timestamp(run_date)
    start_ts = pd.Timestamp(_rolling_window_start_date(run_date, backfill_years))
    mask = (idx >= start_ts) & (idx <= end_ts)
    window = frame.loc[mask]
    if prior_rows <= 0 or window.empty:
        return window

    prior = frame.loc[idx < start_ts].tail(prior_rows)
    if prior.empty:
        return window

    return pd.concat([prior, window]).sort_index()


def _download_price_history_alpha_vantage(
    symbol: str, years_back: int, api_key: str, timeout_seconds: int = 30
):
    """Download adjusted daily prices from Alpha Vantage."""
    _ = years_back  # endpoint returns full adjusted history; trimmed downstream by run_date
    parsed = urlparse(ALPHA_VANTAGE_BASE_URL)
    if parsed.scheme != "https" or parsed.netloc != "www.alphavantage.co":
        raise RuntimeError("Invalid Alpha Vantage base URL configuration.")

    params = {
        "function": "TIME_SERIES_DAILY_ADJUSTED",
        "symbol": symbol,
        "outputsize": "full",
        "apikey": api_key,
    }
    try:
        response = requests.get(
            ALPHA_VANTAGE_BASE_URL,
            params=params,
            timeout=(5, timeout_seconds),
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"Alpha Vantage request failed for {symbol}: {exc}") from exc
    except ValueError as exc:
        raise RuntimeError(f"Alpha Vantage invalid JSON for {symbol}: {exc}") from exc

    if "Error Message" in payload:
        raise RuntimeError(payload["Error Message"])
    if "Note" in payload:
        raise RuntimeError(payload["Note"])

    series = payload.get("Time Series (Daily)")
    if not isinstance(series, dict) or not series:
        raise RuntimeError(f"Alpha Vantage returned no daily data for {symbol}")

    rows: List[Dict[str, Any]] = []
    for obs_date, values in series.items():
        rows.append(
            {
                "observation_date": obs_date,
                "Close": float(values.get("5. adjusted close") or values.get("4. close") or 0.0),
                "Dividends": float(values.get("7. dividend amount") or 0.0),
            }
        )
    history = pd.DataFrame(rows)
    if history.empty:
        raise RuntimeError(f"Alpha Vantage history dataframe empty for {symbol}")

    history["observation_date"] = pd.to_datetime(history["observation_date"])
    history = history.set_index("observation_date").sort_index()
    return None, history


def _extract_total_debt(ticker: Any) -> Optional[float]:
    try:
        balance_sheet = ticker.quarterly_balance_sheet
        debt_fields = ["Total Debt", "TotalDebt", "Long Term Debt", "LongTermDebt"]
        for field in debt_fields:
            if field in balance_sheet.index:
                value = balance_sheet.loc[field].iloc[0]
                if value is None:
                    return None
                return float(value)
    except Exception:  # pragma: no cover - upstream schema dependent
        return None
    return None


def _to_float_or_none(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _download_overview_alpha_vantage(symbol: str, api_key: str) -> Dict[str, Any]:
    """Fetch Alpha Vantage OVERVIEW payload for fundamental snapshot fields."""
    params = {
        "function": "OVERVIEW",
        "symbol": symbol,
        "apikey": api_key,
    }
    response = requests.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=(5, 30))
    response.raise_for_status()
    payload = response.json()
    if "Error Message" in payload:
        raise RuntimeError(payload["Error Message"])
    if "Note" in payload:
        raise RuntimeError(payload["Note"])
    if not isinstance(payload, dict):
        raise RuntimeError("Alpha Vantage OVERVIEW returned invalid payload")
    return payload


def _download_balance_sheet_alpha_vantage(symbol: str, api_key: str) -> Dict[str, Any]:
    """Fetch Alpha Vantage BALANCE_SHEET payload for equity fields."""
    params = {
        "function": "BALANCE_SHEET",
        "symbol": symbol,
        "apikey": api_key,
    }
    response = requests.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=(5, 30))
    response.raise_for_status()
    payload = response.json()
    if "Error Message" in payload:
        raise RuntimeError(payload["Error Message"])
    if "Note" in payload:
        raise RuntimeError(payload["Note"])
    if not isinstance(payload, dict):
        raise RuntimeError("Alpha Vantage BALANCE_SHEET returned invalid payload")
    return payload


def _download_income_statement_alpha_vantage(symbol: str, api_key: str) -> Dict[str, Any]:
    """Fetch Alpha Vantage INCOME_STATEMENT payload for EBITDA/revenue fields."""
    params = {
        "function": "INCOME_STATEMENT",
        "symbol": symbol,
        "apikey": api_key,
    }
    response = requests.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=(5, 30))
    response.raise_for_status()
    payload = response.json()
    if "Error Message" in payload:
        raise RuntimeError(payload["Error Message"])
    if "Note" in payload:
        raise RuntimeError(payload["Note"])
    if not isinstance(payload, dict):
        raise RuntimeError("Alpha Vantage INCOME_STATEMENT returned invalid payload")
    return payload


def _parse_iso_date(value: Any) -> Optional[datetime]:
    raw = str(value or "").strip()[:10]
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None


def _shift_months(d: datetime, months: int) -> datetime:
    """Shift by calendar months with day clamped to month-end."""
    total = d.year * 12 + (d.month - 1) + months
    year = total // 12
    month = (total % 12) + 1
    first_of_target = datetime(year, month, 1)
    if month == 12:
        next_month = datetime(year + 1, 1, 1)
    else:
        next_month = datetime(year, month + 1, 1)
    month_end_day = (next_month - timedelta(days=1)).day
    day = min(d.day, month_end_day)
    return first_of_target.replace(day=day)


def _rolling_window_start_date(run_date: str, backfill_years: int) -> str:
    run_dt = _parse_iso_date(run_date)
    if run_dt is None:
        return run_date
    months = 12 * max(int(backfill_years), 0)
    return _shift_months(run_dt, -months).strftime("%Y-%m-%d")


def _in_backfill_window(report_date: Any, run_date: str, backfill_years: int) -> bool:
    report_dt = _parse_iso_date(report_date)
    run_dt = _parse_iso_date(run_date)
    if report_dt is None or run_dt is None:
        return False
    start_dt = _parse_iso_date(_rolling_window_start_date(run_date, backfill_years))
    if start_dt is None:
        return False
    return start_dt <= report_dt <= run_dt


def _pit_fallback_days(config: Optional[Dict[str, Any]] = None) -> int:
    try:
        days = int(((config or {}).get("edgar") or {}).get("pit_fallback_days", 45))
    except (TypeError, ValueError):
        return 45
    return max(0, days)


def _fallback_financial_publish_date(
    report_date: Optional[str], *, config: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    report_dt = _parse_iso_date(report_date)
    if report_dt is None:
        return None
    return (report_dt + timedelta(days=_pit_fallback_days(config))).strftime("%Y-%m-%d")


def _build_quarterly_fundamentals_from_av_balance_sheet(
    balance_sheet: Dict[str, Any],
    *,
    run_date: str,
    backfill_years: int,
    currency: Optional[str],
    metric_definition: str,
    income_by_date: Optional[Dict[str, Dict[str, Optional[float]]]] = None,
    snapshot_ebitda: Optional[float] = None,
    snapshot_revenue: Optional[float] = None,
) -> List[Dict[str, Any]]:
    quarterly = balance_sheet.get("quarterlyReports") or []
    if not isinstance(quarterly, list):
        return []

    out: List[Dict[str, Any]] = []
    income_lookup = income_by_date or {}
    for report in quarterly:
        if not isinstance(report, dict):
            continue
        report_date = str(report.get("fiscalDateEnding") or "").strip()[:10] or None
        if not report_date or not _in_backfill_window(report_date, run_date, backfill_years):
            continue

        total_equity = _to_float_or_none(
            report.get("totalShareholderEquity") or report.get("totalStockholdersEquity")
        )
        shares_outstanding = _to_float_or_none(report.get("commonStockSharesOutstanding"))
        book_value = None
        if total_equity is not None and shares_outstanding is not None and shares_outstanding > 0:
            book_value = total_equity / shares_outstanding

        income_fields = income_lookup.get(report_date, {})
        out.append(
            {
                "report_date": report_date,
                "total_debt": _to_float_or_none(
                    report.get("totalDebt")
                    or report.get("shortLongTermDebtTotal")
                    or report.get("longTermDebt")
                ),
                "total_shareholder_equity": total_equity,
                "book_value": book_value,
                "shares_outstanding": shares_outstanding,
                "enterprise_ebitda": income_fields.get("enterprise_ebitda"),
                "enterprise_revenue": income_fields.get("enterprise_revenue"),
                "currency": currency,
                "metric_definition": metric_definition,
            }
        )

    out.sort(key=lambda x: str(x.get("report_date") or ""))
    return out


def _build_quarterly_income_map_from_av_income_statement(
    income_statement: Dict[str, Any],
    *,
    run_date: str,
    backfill_years: int,
) -> Dict[str, Dict[str, Optional[float]]]:
    quarterly = income_statement.get("quarterlyReports") or []
    if not isinstance(quarterly, list):
        return {}

    out: Dict[str, Dict[str, Optional[float]]] = {}
    for report in quarterly:
        if not isinstance(report, dict):
            continue
        report_date = str(report.get("fiscalDateEnding") or "").strip()[:10] or None
        if not report_date or not _in_backfill_window(report_date, run_date, backfill_years):
            continue
        out[report_date] = {
            "enterprise_ebitda": _to_float_or_none(report.get("ebitda")),
            "enterprise_revenue": _to_float_or_none(report.get("totalRevenue")),
        }
    return out


def _get_yfinance_quarterly_frame(ticker: Any, attr_names: List[str]) -> pd.DataFrame:
    for attr in attr_names:
        frame = None
        try:
            frame = getattr(ticker, attr)
        except Exception:
            frame = None
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            return frame.copy()
    return pd.DataFrame()


def _map_yfinance_quarter_columns(frame: pd.DataFrame) -> Dict[str, Any]:
    if frame is None or frame.empty:
        return {}
    out: Dict[str, Any] = {}
    for col in frame.columns:
        ts = pd.to_datetime(col, errors="coerce")
        if pd.isna(ts):
            continue
        out[ts.date().isoformat()] = col
    return out


def _extract_yfinance_frame_value(
    frame: pd.DataFrame, column: Any, field_names: List[str]
) -> Optional[float]:
    if frame is None or frame.empty or column is None:
        return None
    for field in field_names:
        if field not in frame.index:
            continue
        value = frame.loc[field, column]
        if isinstance(value, pd.Series):
            value = value.iloc[0]
        parsed = _to_float_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _build_quarterly_fundamentals_from_yfinance_ticker(
    ticker: Any,
    *,
    run_date: str,
    backfill_years: int,
    currency: Optional[str],
    metric_definition: str,
) -> List[Dict[str, Any]]:
    balance_sheet = _get_yfinance_quarterly_frame(
        ticker,
        ["quarterly_balance_sheet"],
    )
    income_stmt = _get_yfinance_quarterly_frame(
        ticker,
        ["quarterly_income_stmt", "quarterly_incomestmt", "quarterly_financials"],
    )

    bs_cols = _map_yfinance_quarter_columns(balance_sheet)
    inc_cols = _map_yfinance_quarter_columns(income_stmt)
    report_dates = sorted(set(bs_cols) | set(inc_cols))
    out: List[Dict[str, Any]] = []

    for report_date in report_dates:
        if not _in_backfill_window(report_date, run_date, backfill_years):
            continue
        bs_col = bs_cols.get(report_date)
        inc_col = inc_cols.get(report_date)
        total_debt = _extract_yfinance_frame_value(
            balance_sheet,
            bs_col,
            ["Total Debt", "TotalDebt", "Long Term Debt", "LongTermDebt"],
        )
        total_equity = _extract_yfinance_frame_value(
            balance_sheet,
            bs_col,
            [
                "Stockholders Equity",
                "Total Stockholder Equity",
                "Total Shareholder Equity",
                "TotalEquityGrossMinorityInterest",
            ],
        )
        shares_outstanding = _extract_yfinance_frame_value(
            balance_sheet,
            bs_col,
            [
                "Common Stock Shares Outstanding",
                "CommonStockSharesOutstanding",
                "Ordinary Shares Number",
                "Share Issued",
            ],
        )
        enterprise_ebitda = _extract_yfinance_frame_value(
            income_stmt,
            inc_col,
            ["EBITDA", "Ebitda"],
        )
        enterprise_revenue = _extract_yfinance_frame_value(
            income_stmt,
            inc_col,
            ["Total Revenue", "TotalRevenue"],
        )
        book_value = None
        if total_equity is not None and shares_outstanding is not None and shares_outstanding > 0:
            book_value = total_equity / shares_outstanding
        if all(
            value is None
            for value in (
                total_debt,
                total_equity,
                shares_outstanding,
                enterprise_ebitda,
                enterprise_revenue,
            )
        ):
            continue
        out.append(
            {
                "report_date": report_date,
                "total_debt": total_debt,
                "total_shareholder_equity": total_equity,
                "book_value": book_value,
                "shares_outstanding": shares_outstanding,
                "enterprise_ebitda": enterprise_ebitda,
                "enterprise_revenue": enterprise_revenue,
                "currency": currency,
                "metric_definition": metric_definition,
            }
        )

    out.sort(key=lambda x: str(x.get("report_date") or ""))
    return out


def _annotate_quarterly_value_sources(
    rows: List[Dict[str, Any]], *, source_name: str
) -> List[Dict[str, Any]]:
    annotated: List[Dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        updated = dict(row)
        source_map = _normalize_text_map(updated.get("value_source_by_metric"))
        provider_values_map = _normalize_provider_values_by_metric(updated.get("provider_values_by_metric"))
        report_date = _coerce_iso_date_text(updated.get("report_date"))
        for key in _SOURCE_A_QUARTERLY_METRIC_KEYS:
            metric_value = _coerce_finite_float(updated.get(key))
            if metric_value is None:
                continue
            if not source_map.get(key):
                source_map[key] = source_name
            metric_provider_map = dict(provider_values_map.get(key) or {})
            metric_provider_map[source_name] = {
                "value": metric_value,
                "report_date": report_date,
            }
            provider_values_map[key] = metric_provider_map
        if source_map:
            updated["value_source_by_metric"] = source_map
        if provider_values_map:
            updated["provider_values_by_metric"] = provider_values_map
        annotated.append(updated)
    return annotated


def _apply_default_publish_dates_to_quarterly_rows(
    rows: List[Dict[str, Any]],
    *,
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    normalized_rows: List[Dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        updated = dict(row)
        report_date = _coerce_iso_date_text(updated.get("report_date"))
        row_publish_date = _coerce_iso_date_text(
            updated.get("publish_date")
            or updated.get("available_date")
            or _fallback_financial_publish_date(report_date, config=config)
        )
        if row_publish_date:
            updated["publish_date"] = row_publish_date

        publish_date_map = _normalize_publish_date_by_metric(updated.get("publish_date_by_metric"))
        publish_date_source_map = _normalize_text_map(
            updated.get("publish_date_source_by_metric")
        )
        for key in _SOURCE_A_QUARTERLY_METRIC_KEYS:
            if updated.get(key) is None:
                continue
            if row_publish_date and not publish_date_map.get(key):
                publish_date_map[key] = row_publish_date
            if publish_date_map.get(key) and not publish_date_source_map.get(key):
                publish_date_source_map[key] = (
                    "provider_date"
                    if _coerce_iso_date_text(updated.get("publish_date"))
                    or _coerce_iso_date_text(updated.get("available_date"))
                    else "fallback_45d"
                )

        if publish_date_map:
            updated["publish_date_by_metric"] = publish_date_map
            updated["publish_date"] = max(publish_date_map.values())
        if publish_date_source_map:
            updated["publish_date_source_by_metric"] = publish_date_source_map
        normalized_rows.append(updated)
    return normalized_rows


def _merge_quarterly_fundamentals(
    existing: List[Dict[str, Any]], incoming: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    if not existing:
        return sorted(incoming, key=lambda x: str(x.get("report_date") or ""))
    merged: Dict[str, Dict[str, Any]] = {
        str(row.get("report_date") or ""): dict(row) for row in existing if row.get("report_date")
    }
    for row in incoming:
        report_date = str(row.get("report_date") or "")
        if not report_date:
            continue
        if report_date not in merged:
            merged[report_date] = dict(row)
            continue
        current = merged[report_date]
        for key, value in row.items():
            if key in _SOURCE_A_QUARTERLY_PROVENANCE_KEYS:
                if key == "provider_values_by_metric":
                    current_map = _normalize_provider_values_by_metric(current.get(key))
                    incoming_map = _normalize_provider_values_by_metric(value)
                    merged_map = {
                        metric_key: dict(provider_map)
                        for metric_key, provider_map in current_map.items()
                    }
                    for metric_key, provider_map in incoming_map.items():
                        merged_provider_map = dict(merged_map.get(metric_key) or {})
                        for provider_name, provider_payload in provider_map.items():
                            if provider_name not in merged_provider_map:
                                merged_provider_map[provider_name] = provider_payload
                        if merged_provider_map:
                            merged_map[metric_key] = merged_provider_map
                    if merged_map:
                        current[key] = merged_map
                    continue
                current_map = (
                    _normalize_publish_date_by_metric(current.get(key))
                    if key == "publish_date_by_metric"
                    else _normalize_text_map(current.get(key))
                )
                incoming_map = (
                    _normalize_publish_date_by_metric(value)
                    if key == "publish_date_by_metric"
                    else _normalize_text_map(value)
                )
                merged_map = dict(current_map)
                for metric_key, metric_value in incoming_map.items():
                    if metric_key not in merged_map:
                        merged_map[metric_key] = metric_value
                if merged_map:
                    current[key] = merged_map
                continue
            if current.get(key) is None and value is not None:
                current[key] = value
    return sorted(merged.values(), key=lambda x: str(x.get("report_date") or ""))


def _has_complete_enterprise_pair(row: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(row, dict):
        return False
    return (
        _to_float_or_none(row.get("enterprise_ebitda")) is not None
        and _to_float_or_none(row.get("enterprise_revenue")) is not None
    )


def _set_enterprise_pair(target: Dict[str, Any], source: Optional[Dict[str, Any]]) -> None:
    if not isinstance(source, dict):
        target["enterprise_ebitda"] = None
        target["enterprise_revenue"] = None
        return
    target["enterprise_ebitda"] = source.get("enterprise_ebitda")
    target["enterprise_revenue"] = source.get("enterprise_revenue")


def _apply_enterprise_pair_priority(
    quarterly_fundamentals: List[Dict[str, Any]],
    *,
    av_quarterly: List[Dict[str, Any]],
    yf_quarterly: List[Dict[str, Any]],
) -> None:
    if not quarterly_fundamentals:
        return

    av_by_date = {
        str(row.get("report_date") or ""): row for row in av_quarterly if row.get("report_date")
    }
    yf_by_date = {
        str(row.get("report_date") or ""): row for row in yf_quarterly if row.get("report_date")
    }

    for row in quarterly_fundamentals:
        report_date = str(row.get("report_date") or "")
        selected: Optional[Dict[str, Any]] = None
        av_row = av_by_date.get(report_date)
        yf_row = yf_by_date.get(report_date)

        if _has_complete_enterprise_pair(yf_row):
            selected = yf_row
        elif _has_complete_enterprise_pair(av_row):
            selected = av_row

        _set_enterprise_pair(row, selected)


def _extract_fundamentals_from_yfinance_ticker(ticker: Any) -> Dict[str, Any]:
    """Extract fundamental snapshot fields from yfinance ticker object."""
    info = {}
    try:
        info = ticker.info or {}
    except Exception:
        info = {}

    total_debt = _extract_total_debt(ticker)
    if total_debt is None:
        total_debt = _to_float_or_none(info.get("totalDebt"))

    total_shareholder_equity = _to_float_or_none(
        info.get("totalStockholderEquity") or info.get("totalShareholderEquity")
    )
    if total_shareholder_equity is None:
        try:
            balance_sheet = ticker.quarterly_balance_sheet
            equity_fields = [
                "Stockholders Equity",
                "Total Stockholder Equity",
                "Total Shareholder Equity",
                "TotalEquityGrossMinorityInterest",
            ]
            for field in equity_fields:
                if field in balance_sheet.index:
                    total_shareholder_equity = _to_float_or_none(balance_sheet.loc[field].iloc[0])
                    if total_shareholder_equity is not None:
                        break
        except Exception:
            logger.debug(
                "source_a_equity_fallback_failed reason=quarterly_balance_sheet_unavailable"
            )

    return {
        "total_debt": total_debt,
        "total_shareholder_equity": total_shareholder_equity,
        "book_value": _to_float_or_none(info.get("bookValue")),
        "shares_outstanding": _to_float_or_none(info.get("sharesOutstanding")),
        "enterprise_ebitda": None,
        "enterprise_revenue": None,
        "report_date": str(info.get("mostRecentQuarter") or "").strip()[:10] or None,
        "currency": str(info.get("currency") or "").strip().upper() or None,
        "metric_definition": "provider_reported",
    }


def _apply_snapshot_fallback_to_latest_quarter(
    quarterly_fundamentals: List[Dict[str, Any]],
    *,
    snapshot_ebitda: Optional[float],
    snapshot_revenue: Optional[float],
) -> None:
    _ = (quarterly_fundamentals, snapshot_ebitda, snapshot_revenue)


def _extract_fundamentals(
    symbol: str,
    ticker: Any,
    config: Dict[str, Any],
    run_date: Optional[str] = None,
    backfill_years: int = 1,
) -> Dict[str, Any]:
    """Extract fundamentals with statement-first order and fallback layers."""
    out: Dict[str, Any] = {
        "total_debt": None,
        "total_shareholder_equity": None,
        "book_value": None,
        "shares_outstanding": None,
        "enterprise_ebitda": None,
        "enterprise_revenue": None,
        "report_date": None,
        "currency": None,
        "metric_definition": "provider_reported",
        "quarterly_fundamentals": [],
    }
    av_quarterly: List[Dict[str, Any]] = []
    yf_quarterly: List[Dict[str, Any]] = []

    # 1) yfinance first: this is the primary free provider for Source A.
    yf_ticker = ticker
    if yf_ticker is None:
        try:
            import yfinance as yf

            yf_ticker = yf.Ticker(symbol)
        except Exception:
            yf_ticker = None
    if yf_ticker is not None:
        yf_quarterly = _build_quarterly_fundamentals_from_yfinance_ticker(
            yf_ticker,
            run_date=str(run_date or ""),
            backfill_years=backfill_years,
            currency=out.get("currency"),
            metric_definition=str(out.get("metric_definition") or "provider_reported"),
        )
        yf_quarterly = _annotate_quarterly_value_sources(yf_quarterly, source_name="yfinance")
        if yf_quarterly:
            out["quarterly_fundamentals"] = _merge_quarterly_fundamentals(
                out.get("quarterly_fundamentals") or [],
                yf_quarterly,
            )
            latest_quarter = out["quarterly_fundamentals"][-1]
            for key in (
                "total_debt",
                "total_shareholder_equity",
                "book_value",
                "shares_outstanding",
                "enterprise_ebitda",
                "enterprise_revenue",
            ):
                if out.get(key) is None:
                    out[key] = latest_quarter.get(key)
            if out.get("report_date") is None:
                latest_report_date = str(latest_quarter.get("report_date") or "").strip()
                out["report_date"] = latest_report_date or None
            if out.get("currency") is None:
                out["currency"] = latest_quarter.get("currency")
        yf_vals = _extract_fundamentals_from_yfinance_ticker(yf_ticker)
        for key in out:
            if out[key] is None:
                out[key] = yf_vals.get(key)

    # 2) Alpha Vantage fills remaining gaps only.
    api_key = _resolve_alpha_key(config)
    if api_key and any(
        out.get(k) is None
        for k in (
            "total_debt",
            "total_shareholder_equity",
            "book_value",
            "shares_outstanding",
            "enterprise_ebitda",
            "enterprise_revenue",
            "report_date",
            "currency",
        )
    ):
        income_by_date: Dict[str, Dict[str, Optional[float]]] = {}
        try:
            income_statement = _download_income_statement_alpha_vantage(symbol, api_key)
            income_by_date = _build_quarterly_income_map_from_av_income_statement(
                income_statement,
                run_date=str(run_date or ""),
                backfill_years=backfill_years,
            )
        except Exception as exc:
            logger.warning(
                "alpha_vantage_income_statement_failed symbol=%s reason=%r; "
                "keeping yfinance values where available",
                symbol,
                exc,
            )
        try:
            balance_sheet = _download_balance_sheet_alpha_vantage(symbol, api_key)
            av_quarterly = _build_quarterly_fundamentals_from_av_balance_sheet(
                balance_sheet,
                run_date=str(run_date or ""),
                backfill_years=backfill_years,
                currency=out["currency"],
                metric_definition=str(out["metric_definition"] or "provider_reported"),
                income_by_date=income_by_date,
            )
            av_quarterly = _annotate_quarterly_value_sources(
                av_quarterly,
                source_name="alpha_vantage",
            )
            if av_quarterly:
                out["quarterly_fundamentals"] = _merge_quarterly_fundamentals(
                    out.get("quarterly_fundamentals") or [],
                    av_quarterly,
                )
                latest_quarter = out["quarterly_fundamentals"][-1]
                for key in (
                    "total_debt",
                    "total_shareholder_equity",
                    "book_value",
                    "shares_outstanding",
                    "enterprise_ebitda",
                    "enterprise_revenue",
                ):
                    if out.get(key) is None:
                        out[key] = latest_quarter.get(key)
                if out.get("report_date") is None:
                    out["report_date"] = (
                        str(latest_quarter.get("report_date") or "").strip() or None
                    )
                if out.get("currency") is None:
                    out["currency"] = latest_quarter.get("currency")
        except Exception as exc:
            logger.warning(
                "alpha_vantage_balance_sheet_failed symbol=%s reason=%r; "
                "keeping yfinance values where available",
                symbol,
                exc,
            )

        try:
            overview = _download_overview_alpha_vantage(symbol, api_key)
            overview_total_debt = _to_float_or_none(overview.get("TotalDebt"))
            overview_book_value = _to_float_or_none(overview.get("BookValue"))
            overview_shares = _to_float_or_none(overview.get("SharesOutstanding"))
            overview_report_date = str(overview.get("LatestQuarter") or "").strip()[:10] or None
            overview_currency = str(overview.get("Currency") or "").strip().upper() or None

            if out["total_debt"] is None:
                out["total_debt"] = overview_total_debt
            if out["book_value"] is None:
                out["book_value"] = overview_book_value
            if out["shares_outstanding"] is None:
                out["shares_outstanding"] = overview_shares
            if out["report_date"] is None:
                out["report_date"] = overview_report_date
            if out["currency"] is None:
                out["currency"] = overview_currency
        except Exception as exc:
            logger.warning(
                "alpha_vantage_overview_failed symbol=%s reason=%r; "
                "keeping yfinance values where available",
                symbol,
                exc,
            )

    _apply_enterprise_pair_priority(
        out["quarterly_fundamentals"],
        av_quarterly=av_quarterly,
        yf_quarterly=yf_quarterly,
    )
    out["quarterly_fundamentals"] = _apply_default_publish_dates_to_quarterly_rows(
        out["quarterly_fundamentals"],
        config=config,
    )

    out["enterprise_ebitda"] = None
    out["enterprise_revenue"] = None
    if out["quarterly_fundamentals"]:
        latest_quarter = out["quarterly_fundamentals"][-1]
        if _has_complete_enterprise_pair(latest_quarter):
            out["enterprise_ebitda"] = latest_quarter.get("enterprise_ebitda")
            out["enterprise_revenue"] = latest_quarter.get("enterprise_revenue")
        out["publish_date"] = latest_quarter.get("publish_date")
        out["publish_date_by_metric"] = dict(latest_quarter.get("publish_date_by_metric") or {})
        out["publish_date_source_by_metric"] = dict(
            latest_quarter.get("publish_date_source_by_metric") or {}
        )
        out["value_source_by_metric"] = dict(latest_quarter.get("value_source_by_metric") or {})
        out["provider_values_by_metric"] = _normalize_provider_values_by_metric(
            latest_quarter.get("provider_values_by_metric")
        )

    return out


def _minio_config(config: Dict[str, Any]) -> Dict[str, Any]:
    minio_cfg = dict(config.get("minio") or {})
    minio_cfg["endpoint"] = os.getenv("MINIO_ENDPOINT", minio_cfg.get("endpoint"))
    minio_cfg["access_key"] = os.getenv("MINIO_ACCESS_KEY", minio_cfg.get("access_key"))
    minio_cfg["secret_key"] = os.getenv("MINIO_SECRET_KEY", minio_cfg.get("secret_key"))
    minio_cfg["bucket"] = os.getenv("MINIO_BUCKET", minio_cfg.get("bucket"))
    endpoint = str(minio_cfg.get("endpoint", "")).replace("http://", "").replace("https://", "")
    minio_cfg["endpoint"] = endpoint
    return minio_cfg


def _raw_legacy_object_path(symbol: str, run_date: str) -> str:
    return (
        "raw/source_a/pricing_fundamentals/"
        f"run_date={run_date}/year={run_date[:4]}/symbol={symbol}.json"
    )


def _raw_market_object_path(symbol: str, run_date: str) -> str:
    return f"raw/source_a/market/run_date={run_date}/year={run_date[:4]}/symbol={symbol}.json"


def _raw_financial_object_path(symbol: str, run_date: str) -> str:
    return (
        f"raw/source_a/financial/run_date={run_date}/year={run_date[:4]}/symbol={symbol}.json"
    )


def _load_json_object_from_minio(
    *,
    minio_cfg: Dict[str, Any],
    object_path: str,
) -> Optional[Dict[str, Any]]:
    try:
        from minio import Minio

        client = Minio(
            endpoint=minio_cfg["endpoint"],
            access_key=minio_cfg["access_key"],
            secret_key=minio_cfg["secret_key"],
            secure=minio_cfg.get("secure", False),
        )
        obj = client.get_object(minio_cfg["bucket"], object_path)
        try:
            payload = json.loads(obj.read().decode("utf-8"))
        finally:
            obj.close()
            obj.release_conn()
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _save_json_object_to_minio(
    *,
    minio_cfg: Dict[str, Any],
    object_path: str,
    payload: Dict[str, Any],
) -> None:
    from minio import Minio

    client = Minio(
        endpoint=minio_cfg["endpoint"],
        access_key=minio_cfg["access_key"],
        secret_key=minio_cfg["secret_key"],
        secure=minio_cfg.get("secure", False),
    )
    bucket = minio_cfg["bucket"]
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)

    data = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
    client.put_object(
        bucket,
        object_path,
        data=BytesIO(data),
        length=len(data),
        content_type="application/json",
    )


def _split_source_a_payload(
    normalized_payload: Dict[str, Any], *, symbol: str, run_date: str
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    market_payload = {
        "symbol": symbol,
        "run_date": run_date,
        "as_of_date": run_date,
        "rows": int(normalized_payload.get("rows") or 0),
        "history": list(normalized_payload.get("history") or []),
        "source_used": normalized_payload.get("source_used"),
        "normalized_schema_version": _SOURCE_A_RAW_SCHEMA_VERSION,
        "provider_payload_version": normalized_payload.get("provider_payload_version"),
        "schema_validation_status": normalized_payload.get("schema_validation_status"),
        "schema_validation_errors": list(normalized_payload.get("schema_validation_errors") or []),
        "raw_layer": "market",
    }
    financial_payload = {
        "symbol": symbol,
        "run_date": run_date,
        "as_of_date": run_date,
        "fundamentals": dict(normalized_payload.get("fundamentals") or {}),
        "total_debt": normalized_payload.get("total_debt"),
        "source_used": normalized_payload.get("source_used"),
        "normalized_schema_version": _SOURCE_A_RAW_SCHEMA_VERSION,
        "provider_payload_version": normalized_payload.get("provider_payload_version"),
        "schema_validation_status": normalized_payload.get("schema_validation_status"),
        "schema_validation_errors": list(normalized_payload.get("schema_validation_errors") or []),
        "raw_layer": "financial",
        "merge_policy": {
            "market_values": ["yfinance", "alpha_vantage"],
            "financial_values": ["yfinance", "alpha_vantage", "edgar_xbrl_overlap"],
            "financial_publish_date": ["edgar_xbrl", "provider_date", "fallback"],
        },
    }
    return market_payload, financial_payload


def _combine_source_a_payloads(
    *,
    symbol: str,
    run_date: str,
    market_payload: Optional[Dict[str, Any]],
    financial_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    market_status = str((market_payload or {}).get("schema_validation_status") or "").strip()
    financial_status = str((financial_payload or {}).get("schema_validation_status") or "").strip()
    combined_status = "valid"
    if any(status and status != "valid" for status in (market_status, financial_status)):
        combined_status = financial_status if financial_status and financial_status != "valid" else market_status
    return {
        "symbol": symbol,
        "run_date": run_date,
        "rows": int((market_payload or {}).get("rows") or 0),
        "history": list((market_payload or {}).get("history") or []),
        "fundamentals": dict((financial_payload or {}).get("fundamentals") or {}),
        "total_debt": (financial_payload or {}).get("total_debt"),
        "source_used": (market_payload or {}).get("source_used")
        or (financial_payload or {}).get("source_used"),
        "normalized_schema_version": _SOURCE_A_RAW_SCHEMA_VERSION,
        "provider_payload_version": (market_payload or {}).get("provider_payload_version")
        or (financial_payload or {}).get("provider_payload_version"),
        "schema_validation_status": combined_status,
        "schema_validation_errors": sorted(
            set(
                list((market_payload or {}).get("schema_validation_errors") or [])
                + list((financial_payload or {}).get("schema_validation_errors") or [])
            )
        ),
    }


def _load_raw_from_minio(
    config: Dict[str, Any], symbol: str, run_date: str
) -> Optional[Dict[str, Any]]:
    minio_cfg = _minio_config(config)
    required = ["endpoint", "access_key", "secret_key", "bucket"]
    if not all(minio_cfg.get(k) for k in required):
        return None

    market_payload = _load_json_object_from_minio(
        minio_cfg=minio_cfg,
        object_path=_raw_market_object_path(symbol, run_date),
    )
    financial_payload = _load_json_object_from_minio(
        minio_cfg=minio_cfg,
        object_path=_raw_financial_object_path(symbol, run_date),
    )

    if market_payload or financial_payload:
        payload = _combine_source_a_payloads(
            symbol=symbol,
            run_date=run_date,
            market_payload=market_payload,
            financial_payload=financial_payload,
        )
    else:
        payload = _load_json_object_from_minio(
            minio_cfg=minio_cfg,
            object_path=_raw_legacy_object_path(symbol, run_date),
        )
        if payload is None:
            return None
    return _normalize_source_a_payload(payload, symbol=symbol, run_date=run_date)


def _save_raw_to_minio(
    config: Dict[str, Any],
    symbol: str,
    run_date: str,
    payload: Dict[str, Any],
) -> None:
    minio_cfg = _minio_config(config)
    required = ["endpoint", "access_key", "secret_key", "bucket"]
    if not all(minio_cfg.get(k) for k in required):
        return

    try:
        normalized_payload = _normalize_source_a_payload(payload, symbol=symbol, run_date=run_date)
        market_payload, financial_payload = _split_source_a_payload(
            normalized_payload,
            symbol=symbol,
            run_date=run_date,
        )
        _save_json_object_to_minio(
            minio_cfg=minio_cfg,
            object_path=_raw_market_object_path(symbol, run_date),
            payload=market_payload,
        )
        _save_json_object_to_minio(
            minio_cfg=minio_cfg,
            object_path=_raw_financial_object_path(symbol, run_date),
            payload=financial_payload,
        )
    except Exception as exc:  # pragma: no cover - external service dependent
        logger.warning("source_a raw archive skipped for %s: %r", symbol, exc)


def _build_edgar_enrichment_for_source_a_raw(
    edgar_records: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Dict[str, Dict[str, Any]]]]:
    by_symbol: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {}
    for record in edgar_records or []:
        symbol = str(record.get("symbol") or "").strip().upper()
        report_date = _coerce_iso_date_text(record.get("report_date"))
        metric_name = str(record.get("metric_name") or "").strip()
        publish_date = _coerce_iso_date_text(record.get("publish_date"))
        metric_value = _coerce_finite_float(record.get("metric_value"))
        value_source = str(record.get("source") or "edgar_xbrl").strip() or "edgar_xbrl"
        publish_date_source = (
            str(record.get("publish_date_source") or "edgar_xbrl").strip() or "edgar_xbrl"
        )
        quarterly_key = _SOURCE_A_EDGAR_RAW_PUBLISH_DATE_MAP.get(metric_name)
        if not symbol or not report_date or not publish_date or quarterly_key is None:
            continue
        symbol_map = by_symbol.setdefault(symbol, {})
        report_map = symbol_map.setdefault(report_date, {})
        existing = report_map.get(quarterly_key)
        if existing is None or publish_date < str(existing.get("publish_date") or ""):
            report_map[quarterly_key] = {
                "publish_date": publish_date,
                "metric_value": metric_value,
                "value_source": value_source,
                "publish_date_source": publish_date_source,
            }

    for symbol_map in by_symbol.values():
        for report_map in symbol_map.values():
            equity_ref = report_map.get("total_shareholder_equity")
            shares_ref = report_map.get("shares_outstanding")
            equity_date = str((equity_ref or {}).get("publish_date") or "")
            shares_date = str((shares_ref or {}).get("publish_date") or "")
            if equity_date and shares_date:
                report_map["book_value"] = {
                    "publish_date": max(equity_date, shares_date),
                    "metric_value": None,
                    "value_source": "derived_from_core_metrics",
                }
    return by_symbol


def enrich_source_a_raw_with_edgar_publish_dates(
    config: Dict[str, Any],
    run_date: str,
    edgar_records: List[Dict[str, Any]],
) -> Dict[str, int]:
    by_symbol = _build_edgar_enrichment_for_source_a_raw(edgar_records)
    stats = {
        "symbols_with_edgar_dates": int(len(by_symbol)),
        "raw_payloads_updated": 0,
        "quarter_rows_updated": 0,
        "payloads_missing": 0,
    }
    if not by_symbol:
        return stats

    for symbol, report_dates in by_symbol.items():
        payload = _load_raw_from_minio(config, symbol, run_date)
        if not payload:
            stats["payloads_missing"] += 1
            continue

        fundamentals = dict(payload.get("fundamentals") or {})
        quarterly_fundamentals = list(fundamentals.get("quarterly_fundamentals") or [])
        if not quarterly_fundamentals:
            continue

        payload_changed = False
        updated_rows = 0
        for row in quarterly_fundamentals:
            report_date = _coerce_iso_date_text(row.get("report_date"))
            if not report_date:
                continue
            edgar_metric_map = report_dates.get(report_date)
            if not edgar_metric_map:
                continue

            current_publish_map = _normalize_publish_date_by_metric(
                row.get("publish_date_by_metric")
            )
            current_publish_source_map = _normalize_text_map(
                row.get("publish_date_source_by_metric")
            )
            current_value_source_map = _normalize_text_map(row.get("value_source_by_metric"))
            current_provider_values_map = _normalize_provider_values_by_metric(
                row.get("provider_values_by_metric")
            )
            merged_publish_map = dict(current_publish_map)
            merged_publish_source_map = dict(current_publish_source_map)
            merged_value_source_map = dict(current_value_source_map)
            merged_provider_values_map = {
                metric_key: dict(provider_map)
                for metric_key, provider_map in current_provider_values_map.items()
            }
            row_changed = False
            for metric_key, edgar_ref in edgar_metric_map.items():
                publish_date = str(edgar_ref.get("publish_date") or "").strip()
                value_source = str(edgar_ref.get("value_source") or "edgar_xbrl").strip() or "edgar_xbrl"
                if merged_publish_map.get(metric_key) != publish_date:
                    merged_publish_map[metric_key] = publish_date
                    row_changed = True
                publish_date_source = (
                    str(edgar_ref.get("publish_date_source") or "edgar_xbrl").strip()
                    or "edgar_xbrl"
                )
                if merged_publish_source_map.get(metric_key) != publish_date_source:
                    merged_publish_source_map[metric_key] = publish_date_source
                    row_changed = True
                metric_value = edgar_ref.get("metric_value")
                current_value = _coerce_finite_float(row.get(metric_key))
                current_source = (
                    merged_value_source_map.get(metric_key)
                    or current_value_source_map.get(metric_key)
                    or ""
                )
                if (
                    current_value is not None
                    and current_source
                    and current_source not in (merged_provider_values_map.get(metric_key) or {})
                ):
                    metric_provider_map = dict(merged_provider_values_map.get(metric_key) or {})
                    metric_provider_map[current_source] = {
                        "value": current_value,
                        "report_date": report_date,
                    }
                    merged_provider_values_map[metric_key] = metric_provider_map
                    row_changed = True
                if metric_value is not None and row.get(metric_key) != metric_value:
                    row[metric_key] = metric_value
                    row_changed = True
                if (
                    metric_value is not None
                    and merged_value_source_map.get(metric_key) != value_source
                ):
                    merged_value_source_map[metric_key] = value_source
                    row_changed = True
                if metric_value is not None:
                    metric_provider_map = dict(merged_provider_values_map.get(metric_key) or {})
                    metric_provider_map[value_source] = {
                        "value": metric_value,
                        "report_date": report_date,
                    }
                    if metric_provider_map != merged_provider_values_map.get(metric_key):
                        merged_provider_values_map[metric_key] = metric_provider_map
                    row_changed = True

            equity = _coerce_finite_float(row.get("total_shareholder_equity"))
            shares = _coerce_finite_float(row.get("shares_outstanding"))
            if equity is not None and shares is not None and shares > 0:
                derived_book_value = equity / shares
                if row.get("book_value") != derived_book_value:
                    row["book_value"] = derived_book_value
                    row_changed = True
                book_value_publish_date = max(
                    merged_publish_map.get("total_shareholder_equity") or "",
                    merged_publish_map.get("shares_outstanding") or "",
                )
                if book_value_publish_date and merged_publish_map.get("book_value") != book_value_publish_date:
                    merged_publish_map["book_value"] = book_value_publish_date
                    row_changed = True
                if book_value_publish_date and merged_publish_source_map.get("book_value") != "derived_from_core_metrics":
                    merged_publish_source_map["book_value"] = "derived_from_core_metrics"
                    row_changed = True
                if merged_value_source_map.get("book_value") != "derived_from_core_metrics":
                    merged_value_source_map["book_value"] = "derived_from_core_metrics"
                    row_changed = True
                book_value_provider_map = dict(merged_provider_values_map.get("book_value") or {})
                new_book_value_provider_map = dict(book_value_provider_map)
                new_book_value_provider_map["derived_from_core_metrics"] = {
                    "value": derived_book_value,
                    "report_date": report_date,
                }
                if new_book_value_provider_map != book_value_provider_map:
                    merged_provider_values_map["book_value"] = new_book_value_provider_map
                    row_changed = True

            if (
                not row_changed
                and merged_publish_map == current_publish_map
                and merged_publish_source_map == current_publish_source_map
                and merged_value_source_map == current_value_source_map
                and merged_provider_values_map == current_provider_values_map
            ):
                continue

            row["publish_date_by_metric"] = merged_publish_map
            row["publish_date_source_by_metric"] = merged_publish_source_map
            row["value_source_by_metric"] = merged_value_source_map
            row["provider_values_by_metric"] = merged_provider_values_map
            conservative_row_publish_date = max(merged_publish_map.values())
            current_row_publish_date = _coerce_iso_date_text(
                row.get("publish_date") or row.get("available_date")
            )
            if current_row_publish_date != conservative_row_publish_date:
                row["publish_date"] = conservative_row_publish_date
                row_changed = True
            row["publish_date_source"] = "edgar_enriched"
            payload_changed = True
            updated_rows += 1

            latest_report_date = _coerce_iso_date_text(fundamentals.get("report_date"))
            if latest_report_date and latest_report_date == report_date:
                fundamentals["publish_date"] = conservative_row_publish_date
                fundamentals["publish_date_by_metric"] = merged_publish_map
                fundamentals["publish_date_source_by_metric"] = merged_publish_source_map
                fundamentals["value_source_by_metric"] = merged_value_source_map
                fundamentals["provider_values_by_metric"] = merged_provider_values_map
                for metric_key, source_name in merged_value_source_map.items():
                    if row.get(metric_key) is not None:
                        fundamentals[metric_key] = row.get(metric_key)

        if payload_changed:
            fundamentals["quarterly_fundamentals"] = quarterly_fundamentals
            payload["fundamentals"] = fundamentals
            payload["edgar_publish_dates_enriched"] = True
            payload["edgar_publish_dates_enriched_at"] = str(run_date)
            _save_raw_to_minio(config, symbol, run_date, payload)
            stats["raw_payloads_updated"] += 1
            stats["quarter_rows_updated"] += updated_rows

    return stats


def _compute_momentum_1m(close_series: pd.Series) -> pd.Series:
    return close_series / close_series.shift(20) - 1.0


def _compute_volatility_20d(close_series: pd.Series) -> pd.Series:
    returns = close_series.pct_change()
    return returns.rolling(window=20).std()


def _build_technical_records(
    symbol: str, history: Any, frequency: str, source_label: str
) -> List[Dict[str, Any]]:
    if len(history) < 20:
        return []

    close_series = history.get("Close")
    if close_series is None:
        return []
    close_series = pd.to_numeric(close_series, errors="coerce").dropna()
    close_series = close_series[close_series > 0]
    if len(close_series) < 20:
        return []

    momentum = _compute_momentum_1m(close_series)
    volatility = _compute_volatility_20d(close_series)

    records: List[Dict[str, Any]] = []
    for idx, value in momentum.dropna().items():
        observation_date = idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]
        records.append(
            {
                "symbol": symbol,
                "observation_date": observation_date,
                "factor_name": "momentum_1m",
                "value": float(value),
                "source": source_label,
                "frequency": frequency,
            }
        )
    for idx, value in volatility.dropna().items():
        observation_date = idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]
        records.append(
            {
                "symbol": symbol,
                "observation_date": observation_date,
                "factor_name": "volatility_20d",
                "value": float(value),
                "source": source_label,
                "frequency": frequency,
            }
        )
    return records


def _build_records_from_history(
    symbol: str,
    history: Any,
    run_date: str,
    frequency: str,
    source_label: str = "alpha_vantage",
    emit_start_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    prev_close: Optional[float] = None
    emit_start = str(emit_start_date or "").strip()[:10] or None

    for idx, row in history.iterrows():
        observation_date = idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]

        close = row.get("Close")
        dividends = row.get("Dividends")
        close_v = _to_float_or_none(close)
        daily_return = None
        if close_v is not None and close_v > 0 and prev_close is not None and prev_close > 0:
            daily_return = math.log(close_v / prev_close)

        if emit_start and observation_date < emit_start:
            if close_v is not None and close_v > 0:
                prev_close = close_v
            continue

        records.append(
            {
                "symbol": symbol,
                "observation_date": observation_date,
                "factor_name": "adjusted_close_price",
                "value": close_v,
                "source": source_label,
                "frequency": frequency,
            }
        )
        open_v = _to_float_or_none(row.get("Open"))
        records.append(
            {
                "symbol": symbol,
                "observation_date": observation_date,
                "factor_name": "open_price",
                "value": open_v,
                "source": source_label,
                "frequency": frequency,
            }
        )
        high_v = _to_float_or_none(row.get("High"))
        records.append(
            {
                "symbol": symbol,
                "observation_date": observation_date,
                "factor_name": "high_price",
                "value": high_v,
                "source": source_label,
                "frequency": frequency,
            }
        )
        low_v = _to_float_or_none(row.get("Low"))
        records.append(
            {
                "symbol": symbol,
                "observation_date": observation_date,
                "factor_name": "low_price",
                "value": low_v,
                "source": source_label,
                "frequency": frequency,
            }
        )
        records.append(
            {
                "symbol": symbol,
                "observation_date": observation_date,
                "factor_name": "daily_return",
                "value": daily_return,
                "source": source_label,
                "frequency": frequency,
            }
        )
        records.append(
            {
                "symbol": symbol,
                "observation_date": observation_date,
                "factor_name": "dividend_per_share",
                "value": None if dividends is None else float(dividends),
                "source": source_label,
                "frequency": frequency,
            }
        )
        volume = row.get("Volume")
        volume_v = _to_float_or_none(volume)
        records.append(
            {
                "symbol": symbol,
                "observation_date": observation_date,
                "factor_name": "daily_volume",
                "value": volume_v,
                "source": source_label,
                "frequency": frequency,
            }
        )

        if close_v is not None and close_v > 0:
            prev_close = close_v

    return records


def _build_fundamental_records(
    symbol: str,
    run_date: str,
    frequency: str,
    source_label: str,
    fundamentals: Dict[str, Any],
    backfill_years: int = 1,
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Build atomic financial observation rows for Source A fundamentals."""
    field_map = {
        "total_debt": ("total_debt", "quarterly"),
        "total_shareholder_equity": ("total_shareholder_equity", "quarterly"),
        "book_value": ("book_value", "quarterly"),
        "shares_outstanding": ("shares_outstanding", "quarterly"),
        "enterprise_ebitda": ("enterprise_ebitda", "quarterly"),
        "enterprise_revenue": ("enterprise_revenue", "quarterly"),
    }
    out: List[Dict[str, Any]] = []
    quarterly_fundamentals = fundamentals.get("quarterly_fundamentals") or []

    def _append_from_row(row: Dict[str, Any], report_date: Optional[str]) -> None:
        currency = (
            str(row.get("currency") or fundamentals.get("currency") or "UNKNOWN").strip().upper()
        )
        currency = currency or "UNKNOWN"
        row_publish_date = _coerce_iso_date_text(
            row.get("publish_date")
            or row.get("available_date")
            or _fallback_financial_publish_date(report_date, config=config)
        )
        if not row_publish_date:
            row_publish_date = None
        publish_date_by_metric = _normalize_publish_date_by_metric(
            row.get("publish_date_by_metric")
        )
        value_source_by_metric = _normalize_text_map(row.get("value_source_by_metric"))
        publish_date_source_by_metric = _normalize_text_map(
            row.get("publish_date_source_by_metric")
        )
        metric_definition = (
            str(
                row.get("metric_definition")
                or fundamentals.get("metric_definition")
                or "provider_reported"
            )
            .strip()
            .lower()
        )
        has_enterprise_pair = _has_complete_enterprise_pair(row)
        for key, (factor_name, period_type) in field_map.items():
            if key in {"enterprise_ebitda", "enterprise_revenue"} and not has_enterprise_pair:
                continue
            metric_publish_date = (
                publish_date_by_metric.get(key)
                or publish_date_by_metric.get(factor_name)
                or row_publish_date
            )
            metric_source = (
                value_source_by_metric.get(key)
                or value_source_by_metric.get(factor_name)
                or source_label
            )
            metric_publish_source = (
                publish_date_source_by_metric.get(key)
                or publish_date_source_by_metric.get(factor_name)
                or row.get("publish_date_source")
            )
            out.append(
                {
                    "symbol": symbol,
                    "metric_name": factor_name,
                    "metric_value": row.get(key),
                    "source": metric_source,
                    "value_source": metric_source,
                    "report_date": report_date,
                    "as_of": run_date,
                    "publish_date": metric_publish_date,
                    "publish_date_source": metric_publish_source,
                    "period_type": period_type,
                    "currency": currency,
                    "metric_definition": metric_definition,
                }
            )

    if isinstance(quarterly_fundamentals, list) and quarterly_fundamentals:
        for q_row in quarterly_fundamentals:
            if not isinstance(q_row, dict):
                continue
            report_date = str(q_row.get("report_date") or "").strip()[:10] or None
            if report_date and _in_backfill_window(report_date, run_date, backfill_years):
                _append_from_row(q_row, report_date)

    if not out:
        report_date_raw = fundamentals.get("report_date")
        report_date = str(report_date_raw or "").strip()[:10] or None
        _append_from_row(fundamentals, report_date)
    return out


def _sanitize_alpha_key(value: Any) -> str:
    cleaned = str(value or "").strip()
    if cleaned.upper() in _ALPHA_KEY_PLACEHOLDERS:
        return ""
    return cleaned


def _resolve_alpha_key_with_source(config: Dict[str, Any]) -> tuple[str, str]:
    api_cfg = config.get("api") or {}
    legacy_cfg = config.get("alpha_vantage") or {}

    env_primary = _sanitize_alpha_key(os.getenv("ALPHA_VANTAGE_API_KEY"))
    if env_primary:
        return env_primary, "env"

    env_alias = _sanitize_alpha_key(os.getenv("ALPHA_VANTAGE_KEY"))
    if env_alias:
        return env_alias, "env"

    conf_value = _sanitize_alpha_key(api_cfg.get("alpha_vantage_key") or legacy_cfg.get("api_key"))
    if conf_value:
        return conf_value, "conf"

    return "", "missing"


def _resolve_alpha_key(config: Dict[str, Any]) -> str:
    key, _ = _resolve_alpha_key_with_source(config)
    return key


def _select_source_order(config: Dict[str, Any]) -> List[str]:
    source_cfg = config.get("source_a") or {}
    primary = str(source_cfg.get("primary_source", "yfinance")).strip().lower()
    fallback = bool(source_cfg.get("enable_yfinance_fallback", True))
    order = [primary]
    secondary = "alpha_vantage" if primary == "yfinance" else "yfinance"
    if fallback and secondary not in order:
        order.append(secondary)
    return order


def _select_provider_order_for_symbol(symbol: str, config: Dict[str, Any]) -> List[str]:
    routing_cfg = config.get("routing") or {}

    suffixes = routing_cfg.get("yf_for_suffixes", [".L", ".TO", ".PA", ".DE"])
    symbol_upper = str(symbol).strip().upper()
    has_suffix = any(symbol_upper.endswith(str(s).upper()) for s in suffixes)

    blocklist = set(
        str(x).strip().upper()
        for x in routing_cfg.get(
            "history_blocklist",
            ["ABC", "ADS", "FB", "ATVI", "ABMD", "CELG"],
        )
        if str(x).strip()
    )
    history_policy = str(routing_cfg.get("history_ticker_policy", "skip")).strip().lower()

    if symbol_upper in blocklist:
        if history_policy == "try_yf_only":
            return ["yfinance"]
        return []

    av_regex = str(routing_cfg.get("av_only_if_regex", "^[A-Z0-9]+$")).strip()
    av_allowed = bool(re.fullmatch(av_regex, symbol_upper)) if av_regex else True

    if has_suffix or not av_allowed:
        return ["yfinance"]

    return _select_source_order(config)


def _history_from_payload(payload: Dict[str, Any]) -> pd.DataFrame:
    normalized_payload = _normalize_source_a_payload(
        payload or {},
        symbol=str((payload or {}).get("symbol") or ""),
        run_date=str((payload or {}).get("run_date") or ""),
    )
    rows = normalized_payload.get("history") or []
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    if "Date" in frame.columns:
        idx_col = "Date"
    elif "observation_date" in frame.columns:
        idx_col = "observation_date"
    else:
        idx_col = frame.columns[0]
    frame[idx_col] = pd.to_datetime(frame[idx_col])
    return frame.set_index(idx_col).sort_index()


def _validate_cache_payload(payload: Dict[str, Any], symbol: str, run_date: str) -> List[str]:
    warnings: List[str] = []
    payload_symbol = str(payload.get("symbol") or "").strip().upper()
    if payload_symbol and payload_symbol != str(symbol).strip().upper():
        warnings.append(
            f"symbol_mismatch cache={payload_symbol} request={str(symbol).strip().upper()}"
        )

    payload_run_date = str(payload.get("run_date") or "").strip()
    if payload_run_date and payload_run_date != str(run_date).strip():
        warnings.append(
            f"run_date_mismatch cache={payload_run_date} request={str(run_date).strip()}"
        )

    history_rows = payload.get("history") or []
    row_count = payload.get("rows")
    if isinstance(row_count, int) and row_count >= 0 and row_count != len(history_rows):
        warnings.append(f"rows_mismatch declared={row_count} actual={len(history_rows)}")

    validation_status = str(payload.get("schema_validation_status") or "").strip().lower()
    if validation_status and validation_status != "valid":
        issues = ",".join(str(x) for x in payload.get("schema_validation_errors") or [])
        warnings.append(f"schema_validation_status={validation_status} issues={issues}")

    return warnings


def _download_with_provider(
    symbol: str,
    years_back: int,
    config: Dict[str, Any],
    provider_order: Optional[List[str]] = None,
) -> tuple[str, Any, pd.DataFrame]:
    errors: List[str] = []
    alpha_key, alpha_key_source = _resolve_alpha_key_with_source(config)
    resolved_order = provider_order or _select_source_order(config)
    if "alpha_vantage" in resolved_order and not alpha_key:
        logger.warning(
            "alpha_vantage key missing source=%s "
            "checked=[ALPHA_VANTAGE_API_KEY,ALPHA_VANTAGE_KEY,api.alpha_vantage_key,"
            "alpha_vantage.api_key]",
            alpha_key_source,
        )
    for source in resolved_order:
        try:
            if source == "alpha_vantage":
                if not alpha_key:
                    raise RuntimeError("alpha_vantage key missing")
                ticker, history = _download_price_history_alpha_vantage(
                    symbol, years_back, alpha_key
                )
            elif source == "yfinance":
                ticker, history = _download_price_history(symbol, years_back)
            else:
                raise RuntimeError(f"unsupported provider: {source}")
            return source, ticker, history
        except Exception as exc:
            errors.append(f"{source}: {exc}")
    raise RuntimeError(f"all providers failed for {symbol}; details={errors}")


def _is_symbol_unavailable_error(exc: Exception) -> bool:
    """Return True when the error indicates a stale/delisted symbol.

    These cases should be treated as a routed skip rather than an extractor
    failure because the pipeline can continue safely without degrading the run.
    """
    message = str(exc or "").lower()
    unavailable_markers = (
        "no history returned for symbol=",
        "possibly delisted",
        "no price data found",
        "no data found",
        "no timezone found",
    )
    return any(marker in message for marker in unavailable_markers)


def extract_source_a(
    symbols: List[str],
    run_date: str,
    backfill_years: int,
    frequency: str,
    config: Dict[str, Any] | None = None,
    failed_symbols: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """Extract Source A records for a symbol list.

    Parameters
    ----------
    symbols:
        Target symbol list supplied by upstream universe selection.
    run_date:
        Pipeline run date in ``YYYY-MM-DD`` format.
    backfill_years:
        Historical lookback window in years.
    frequency:
        Scheduling frequency label (daily/weekly/monthly/quarterly/annual).
    config:
        Optional in-memory config. If omitted, config is loaded from file.
    failed_symbols:
        Optional collector list to record failed symbols and reasons.

    Returns
    -------
    list[dict[str, Any]]
        Extracted records in the pre-normalized schema used by downstream
        normalize/quality/load stages.
    """
    if os.getenv("CW1_TEST_MODE") == "1":
        return [
            {
                "symbol": symbol,
                "observation_date": run_date,
                "factor_name": "source_a_metric",
                "value": 1.0,
                "source": "yfinance",
                "frequency": frequency,
            }
            for symbol in symbols
        ]

    cfg = config or load_config("config/conf.yaml")
    target_symbols = filter_symbols(
        symbols=list(symbols or []),
        config=cfg,
        section=None,
        default_skip_suffix=True,
        default_regex=r"^[A-Z0-9]+$",
    )
    if not target_symbols:
        return []
    source_cfg = cfg.get("source_a") or {}
    use_cache = bool(source_cfg.get("use_cache", False))

    records: List[Dict[str, Any]] = []
    for symbol in target_symbols:
        try:
            symbol_records: List[Dict[str, Any]] = []
            provider_order = _select_provider_order_for_symbol(symbol, cfg)
            if not provider_order:
                logger.info("source_a skipped by routing policy for symbol=%s", symbol)
                continue
            payload = _load_raw_from_minio(cfg, symbol, run_date) if use_cache else None
            provider_source = "cache_replay"
            ticker = None

            if payload:
                cache_warnings = _validate_cache_payload(payload, symbol=symbol, run_date=run_date)
                if cache_warnings:
                    logger.warning(
                        "source_a cache_consistency_warning symbol=%s run_date=%s details=%s",
                        symbol,
                        run_date,
                        "; ".join(cache_warnings),
                    )
                history = _history_from_payload(payload)
                fundamentals = payload.get("fundamentals") or {}
                total_debt = fundamentals.get("total_debt", payload.get("total_debt"))
                provider_source = str(payload.get("source_used") or "cache_replay")
            else:
                provider_source, ticker, history = _download_with_provider(
                    symbol, backfill_years, cfg, provider_order=provider_order
                )
                fundamentals = _extract_fundamentals(
                    symbol=symbol,
                    ticker=ticker,
                    config=cfg,
                    run_date=run_date,
                    backfill_years=backfill_years,
                )
                total_debt = fundamentals.get("total_debt")
                payload = {
                    "symbol": symbol,
                    "run_date": run_date,
                    "rows": int(len(history)),
                    "history": history.reset_index().to_dict(orient="records"),
                    "total_debt": total_debt,
                    "fundamentals": fundamentals,
                    "source_used": provider_source,
                }
                payload = _normalize_source_a_payload(payload, symbol=symbol, run_date=run_date)
                _save_raw_to_minio(cfg, symbol, run_date, payload)

            history = _apply_history_window(history, run_date, backfill_years, prior_rows=1)
            emit_start_date = _rolling_window_start_date(run_date, backfill_years)

            symbol_records.extend(
                _build_records_from_history(
                    symbol=symbol,
                    history=history,
                    run_date=run_date,
                    frequency=frequency,
                    source_label=provider_source,
                    emit_start_date=emit_start_date,
                )
            )
            symbol_records.extend(
                _build_technical_records(
                    symbol=symbol,
                    history=history,
                    frequency=frequency,
                    source_label=provider_source,
                )
            )
            symbol_records.extend(
                _build_fundamental_records(
                    symbol=symbol,
                    run_date=run_date,
                    frequency=frequency,
                    source_label=provider_source,
                    fundamentals=fundamentals,
                    backfill_years=backfill_years,
                    config=cfg,
                )
            )
            records.extend(symbol_records)
        except Exception as exc:
            if _is_symbol_unavailable_error(exc):
                logger.warning(
                    "source_a skipped unavailable symbol=%s reason=%s",
                    symbol,
                    exc,
                )
                continue
            logger.error("source_a failed for %s: %r", symbol, exc, exc_info=True)
            if failed_symbols is not None:
                failed_symbols.append({"symbol": symbol, "reason": f"{exc!r}"})

    return records


if __name__ == "__main__":
    today = datetime.today().strftime("%Y-%m-%d")
    out = extract_source_a(["AAPL"], run_date=today, backfill_years=1, frequency="daily")
    print(f"records={len(out)}")
