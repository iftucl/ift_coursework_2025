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


def _json_default(obj: Any) -> Any:
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


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
    """Download price history from yfinance (fallback provider)."""
    import yfinance as yf

    period = f"{max(1, int(years_back))}y"
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            ticker = yf.Ticker(symbol)
            history = ticker.history(period=period, auto_adjust=False)
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
    history: pd.DataFrame, run_date: str, backfill_years: int
) -> pd.DataFrame:
    """Trim history to rolling-month window ending at run_date."""
    if history is None or history.empty:
        return history

    frame = history.sort_index().copy()
    idx = pd.to_datetime(frame.index, errors="coerce")
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert(None)

    end_ts = pd.Timestamp(run_date)
    start_ts = pd.Timestamp(_rolling_window_start_date(run_date, backfill_years))
    mask = (idx >= start_ts) & (idx <= end_ts)
    return frame.loc[mask]


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
    if out:
        latest_report_date = str(out[-1].get("report_date") or "")
        for row in out:
            if str(row.get("report_date") or "") != latest_report_date:
                continue
            if row.get("enterprise_ebitda") is None and snapshot_ebitda is not None:
                row["enterprise_ebitda"] = snapshot_ebitda
            if row.get("enterprise_revenue") is None and snapshot_revenue is not None:
                row["enterprise_revenue"] = snapshot_revenue
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
            "enterprise_ebitda": _to_float_or_none(
                report.get("ebitda") or report.get("ebit") or report.get("operatingIncome")
            ),
            "enterprise_revenue": _to_float_or_none(report.get("totalRevenue")),
        }
    return out


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
        "enterprise_ebitda": _to_float_or_none(info.get("ebitda")),
        "enterprise_revenue": _to_float_or_none(info.get("totalRevenue")),
        "report_date": str(info.get("mostRecentQuarter") or "").strip()[:10] or None,
        "currency": str(info.get("currency") or "").strip().upper() or None,
        "metric_definition": "provider_reported",
    }


def _extract_fundamentals(
    symbol: str,
    ticker: Any,
    config: Dict[str, Any],
    run_date: Optional[str] = None,
    backfill_years: int = 1,
) -> Dict[str, Any]:
    """Extract fundamentals with unified provider order: Alpha Vantage -> yfinance fallback."""
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

    # 1) Alpha Vantage first
    api_key = _resolve_alpha_key(config)
    if api_key:
        try:
            overview = _download_overview_alpha_vantage(symbol, api_key)
            out["total_debt"] = _to_float_or_none(overview.get("TotalDebt"))
            out["book_value"] = _to_float_or_none(overview.get("BookValue"))
            out["shares_outstanding"] = _to_float_or_none(overview.get("SharesOutstanding"))
            out["enterprise_ebitda"] = _to_float_or_none(overview.get("EBITDA"))
            out["enterprise_revenue"] = _to_float_or_none(overview.get("RevenueTTM"))
            out["report_date"] = str(overview.get("LatestQuarter") or "").strip()[:10] or None
            out["currency"] = str(overview.get("Currency") or "").strip().upper() or None
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
                    "falling back to overview snapshot for enterprise metrics",
                    symbol,
                    exc,
                )
            try:
                balance_sheet = _download_balance_sheet_alpha_vantage(symbol, api_key)
                out["quarterly_fundamentals"] = _build_quarterly_fundamentals_from_av_balance_sheet(
                    balance_sheet,
                    run_date=str(run_date or ""),
                    backfill_years=backfill_years,
                    currency=out["currency"],
                    metric_definition=str(out["metric_definition"] or "provider_reported"),
                    income_by_date=income_by_date,
                    snapshot_ebitda=out["enterprise_ebitda"],
                    snapshot_revenue=out["enterprise_revenue"],
                )
                quarterly = balance_sheet.get("quarterlyReports") or []
                if quarterly:
                    latest = quarterly[0] or {}
                    out["total_shareholder_equity"] = _to_float_or_none(
                        latest.get("totalShareholderEquity")
                        or latest.get("totalStockholdersEquity")
                    )
                    if out["report_date"] is None:
                        out["report_date"] = (
                            str(latest.get("fiscalDateEnding") or "").strip()[:10] or None
                        )
            except Exception as exc:
                logger.warning(
                    "alpha_vantage_balance_sheet_failed symbol=%s reason=%r; "
                    "falling back to yfinance equity fields",
                    symbol,
                    exc,
                )
        except Exception as exc:
            logger.warning(
                "alpha_vantage_overview_failed symbol=%s reason=%r; "
                "falling back to yfinance fields",
                symbol,
                exc,
            )

    # 2) yfinance fallback for missing fields only
    if any(
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
        yf_ticker = ticker
        if yf_ticker is None:
            try:
                import yfinance as yf

                yf_ticker = yf.Ticker(symbol)
            except Exception:
                yf_ticker = None
        if yf_ticker is not None:
            yf_vals = _extract_fundamentals_from_yfinance_ticker(yf_ticker)
            for key in out:
                if out[key] is None:
                    out[key] = yf_vals.get(key)

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


def _raw_object_path(symbol: str, run_date: str) -> str:
    return (
        "raw/source_a/pricing_fundamentals/"
        f"run_date={run_date}/year={run_date[:4]}/symbol={symbol}.json"
    )


def _load_raw_from_minio(
    config: Dict[str, Any], symbol: str, run_date: str
) -> Optional[Dict[str, Any]]:
    minio_cfg = _minio_config(config)
    required = ["endpoint", "access_key", "secret_key", "bucket"]
    if not all(minio_cfg.get(k) for k in required):
        return None

    try:
        from minio import Minio

        client = Minio(
            endpoint=minio_cfg["endpoint"],
            access_key=minio_cfg["access_key"],
            secret_key=minio_cfg["secret_key"],
            secure=minio_cfg.get("secure", False),
        )
        obj = client.get_object(minio_cfg["bucket"], _raw_object_path(symbol, run_date))
        try:
            return json.loads(obj.read().decode("utf-8"))
        finally:
            obj.close()
            obj.release_conn()
    except Exception:
        return None


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

        object_path = _raw_object_path(symbol, run_date)
        data = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
        client.put_object(
            bucket,
            object_path,
            data=BytesIO(data),
            length=len(data),
            content_type="application/json",
        )
    except Exception as exc:  # pragma: no cover - external service dependent
        logger.warning("source_a raw archive skipped for %s: %r", symbol, exc)


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
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    prev_close: Optional[float] = None

    for idx, row in history.iterrows():
        observation_date = idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]

        close = row.get("Close")
        dividends = row.get("Dividends")
        close_v = _to_float_or_none(close)
        daily_return = None
        if close_v is not None and close_v > 0 and prev_close is not None and prev_close > 0:
            daily_return = math.log(close_v / prev_close)

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
) -> List[Dict[str, Any]]:
    """Build atomic fundamental factor records at run_date snapshot."""
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
        metric_definition = (
            str(
                row.get("metric_definition")
                or fundamentals.get("metric_definition")
                or "provider_reported"
            )
            .strip()
            .lower()
        )
        for key, (factor_name, period_type) in field_map.items():
            out.append(
                {
                    "symbol": symbol,
                    "observation_date": report_date,
                    "factor_name": factor_name,
                    "value": row.get(key),
                    "source": source_label,
                    "frequency": frequency,
                    "source_report_date": report_date,
                    "report_date": report_date,
                    "as_of": run_date,
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
    primary = str(source_cfg.get("primary_source", "alpha_vantage")).strip().lower()
    fallback = bool(source_cfg.get("enable_yfinance_fallback", True))
    order = [primary]
    if fallback and primary != "yfinance":
        order.append("yfinance")
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
    rows = payload.get("history") or []
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


def extract_source_a(
    symbols: List[str],
    run_date: str,
    backfill_years: int,
    frequency: str,
    config: Dict[str, Any] | None = None,
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
                "source": "alpha_vantage",
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
                _save_raw_to_minio(cfg, symbol, run_date, payload)

            history = _apply_history_window(history, run_date, backfill_years)

            symbol_records.extend(
                _build_records_from_history(
                    symbol=symbol,
                    history=history,
                    run_date=run_date,
                    frequency=frequency,
                    source_label=provider_source,
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
                )
            )
            records.extend(symbol_records)
        except Exception as exc:
            logger.error("source_a failed for %s: %r", symbol, exc, exc_info=True)

    return records


if __name__ == "__main__":
    today = datetime.today().strftime("%Y-%m-%d")
    out = extract_source_a(["AAPL"], run_date=today, backfill_years=1, frequency="daily")
    print(f"records={len(out)}")
