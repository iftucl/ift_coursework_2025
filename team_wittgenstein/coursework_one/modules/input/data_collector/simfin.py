"""SimFin data fetching."""

import logging
from time import monotonic, sleep

import pandas as pd
import requests

from .constants import (
    SIMFIN_STATEMENTS_URL,
    SIMFIN_WEIGHTED_SHARES_URL,
    SimFinServerError,
)

logger = logging.getLogger(__name__)


class SimFinMixin:
    """SimFin fetching methods for DataFetcher."""

    def _fetch_simfin_fundamentals(self, symbol):
        """Fetch quarterly fundamentals from SimFin statements + shares."""
        if not self.simfin_api_key:
            logger.warning(
                "SIMFIN_API_KEY is not set; skipping SimFin fetch for %s",
                symbol,
            )
            return pd.DataFrame()
        statements_payload = self._simfin_get(
            SIMFIN_STATEMENTS_URL,
            params={
                "ticker": symbol,
                "statements": "pl,bs,derived",
                "period": "q1,q2,q3,q4",
            },
        )
        shares_payload = self._simfin_get(
            SIMFIN_WEIGHTED_SHARES_URL,
            params={"ticker": symbol, "period": "q1,q2,q3,q4"},
        )

        if not statements_payload:
            return pd.DataFrame()
        statement_rows = []
        for company in statements_payload:
            ticker = company.get("ticker", symbol)
            statement_dfs = {}
            for stmt in company.get("statements", []):
                stmt_name = str(stmt.get("statement", "")).upper()
                data = stmt.get("data") or []
                columns = stmt.get("columns") or []
                if not data or not columns:
                    continue
                df = pd.DataFrame(data, columns=columns)
                df["symbol"] = ticker
                statement_dfs[stmt_name] = df

            pl = self._simfin_statement_frame(
                statement_dfs.get("PL"),
                {
                    "Fiscal Year": "fiscal_year",
                    "Fiscal Period": "fiscal_quarter",
                    "Report Date": "report_date",
                    "Net Income": "net_income",
                },
                extra_cols=["net_income"],
            )
            bs = self._simfin_statement_frame(
                statement_dfs.get("BS"),
                {
                    "Fiscal Year": "fiscal_year",
                    "Fiscal Period": "fiscal_quarter",
                    "Report Date": "report_date",
                    "Total Assets": "total_assets",
                    "Total Equity": "total_equity",
                },
                extra_cols=["total_assets", "total_equity"],
            )
            derived = self._simfin_statement_frame(
                statement_dfs.get("DERIVED"),
                {
                    "Fiscal Year": "fiscal_year",
                    "Fiscal Period": "fiscal_quarter",
                    "Report Date": "report_date",
                    "Total Debt": "total_debt",
                    "Earnings Per Share, Diluted": "eps",
                },
                extra_cols=["total_debt", "eps"],
            )
            keys = [
                "symbol",
                "fiscal_year",
                "fiscal_quarter",
                "report_date",
            ]
            merged = pl.merge(bs, on=keys, how="outer").merge(
                derived, on=keys, how="outer"
            )
            merged["book_equity"] = merged.get(
                "total_equity", merged.get("book_equity")
            )
            statement_rows.append(merged)

        if not statement_rows:
            return pd.DataFrame()

        out = pd.concat(statement_rows, ignore_index=True)

        shares_df = self._simfin_weighted_shares_frame(
            shares_payload, default_symbol=symbol
        )
        if not shares_df.empty:
            out = out.merge(
                shares_df,
                on=["symbol", "fiscal_year", "fiscal_quarter"],
                how="left",
            )
        else:
            out["shares_outstanding"] = None

        out["report_date"] = pd.to_datetime(out["report_date"], errors="coerce")
        out["fiscal_quarter"] = out["fiscal_quarter"].apply(
            self._normalize_quarter_value
        )
        for col in [
            "total_assets",
            "total_equity",
            "total_debt",
            "net_income",
            "eps",
            "book_equity",
            "shares_outstanding",
        ]:
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")

        out["currency"] = None
        out["source"] = "simfin"
        out = self._ensure_fundamentals_schema(out)
        out = out.dropna(subset=["fiscal_year", "fiscal_quarter"])
        out = out.sort_values("report_date", ascending=False)
        out = out.drop_duplicates(
            subset=["symbol", "fiscal_year", "fiscal_quarter"],
            keep="first",
        )
        return out.reset_index(drop=True)

    def _simfin_get(self, url, params, timeout=20, max_retries=3):
        """Call SimFin API with auth header + free-tier throttle."""
        headers = {
            "Authorization": f"api-key {self.simfin_api_key}",
            "accept": "application/json",
        }
        for attempt in range(max_retries):
            try:
                self._simfin_throttle_wait()
                response = requests.get(
                    url, params=params, headers=headers, timeout=timeout
                )
                status_code = response.status_code

                if status_code == 200:
                    return response.json()

                if status_code == 500:
                    logger.warning(
                        "SimFin returned HTTP 500 (no retry) " "(%s, params=%s)",
                        url,
                        params,
                    )
                    raise SimFinServerError(
                        f"SimFin HTTP 500 for {url} params={params}"
                    )

                if status_code == 429:
                    logger.warning(
                        "SimFin rate limited (429) (%s, params=%s)",
                        url,
                        params,
                    )
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            sleep(float(retry_after))
                        except ValueError:
                            sleep(2.0)
                    else:
                        sleep(2.0)
                    continue

                logger.warning(
                    "SimFin request failed with HTTP %s (%s, params=%s)",
                    status_code,
                    url,
                    params,
                )
                sleep(1.5)
            except requests.RequestException as exc:
                logger.warning(
                    "SimFin request failed (%s, params=%s): %s",
                    url,
                    params,
                    exc,
                )
                sleep(1.5)
        logger.warning("SimFin unavailable after retries (%s)", params)
        return None

    def _simfin_throttle_wait(self):
        """Ensure SimFin request spacing (free tier: 2 req/sec)."""
        with self._simfin_rate_limit_lock:
            elapsed = monotonic() - self._simfin_last_request_ts
            if elapsed < self._simfin_min_interval_seconds:
                sleep(self._simfin_min_interval_seconds - elapsed)
            self._simfin_last_request_ts = monotonic()

    def _simfin_statement_frame(self, df, rename_map, extra_cols):
        """Project and rename one SimFin statement frame safely."""
        base_cols = ["symbol"] + list(rename_map.keys())
        out_cols = [
            "symbol",
            "fiscal_year",
            "fiscal_quarter",
            "report_date",
        ]
        out_cols.extend(extra_cols)
        if df is None or df.empty or not all(col in df.columns for col in base_cols):
            return pd.DataFrame(columns=out_cols)

        out = df[base_cols].copy().rename(columns=rename_map)
        out["fiscal_year"] = pd.to_numeric(out["fiscal_year"], errors="coerce")
        out["fiscal_quarter"] = out["fiscal_quarter"].apply(
            self._normalize_quarter_value
        )
        out["report_date"] = pd.to_datetime(out["report_date"], errors="coerce")
        for col in extra_cols:
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")
        return out[out_cols]

    def _simfin_weighted_shares_frame(self, payload, default_symbol=None):
        """Build quarterly diluted weighted-shares dataframe from SimFin."""
        if not payload:
            return pd.DataFrame(
                columns=[
                    "symbol",
                    "fiscal_year",
                    "fiscal_quarter",
                    "shares_outstanding",
                ]
            )
        shares_df = pd.DataFrame(payload)
        if shares_df.empty:
            return pd.DataFrame(
                columns=[
                    "symbol",
                    "fiscal_year",
                    "fiscal_quarter",
                    "shares_outstanding",
                ]
            )

        rename_map = {
            "ticker": "symbol",
            "fyear": "fiscal_year",
            "period": "fiscal_quarter",
            "diluted": "shares_outstanding",
            "endDate": "share_end_date",
        }
        shares_df = shares_df.rename(columns=rename_map)

        for col in [
            "symbol",
            "fiscal_year",
            "fiscal_quarter",
            "shares_outstanding",
        ]:
            if col not in shares_df.columns:
                shares_df[col] = None
        if default_symbol is not None:
            shares_df["symbol"] = shares_df["symbol"].fillna(default_symbol)
        if "share_end_date" not in shares_df.columns:
            shares_df["share_end_date"] = None

        shares_df["fiscal_year"] = pd.to_numeric(
            shares_df["fiscal_year"], errors="coerce"
        )
        shares_df["fiscal_quarter"] = shares_df["fiscal_quarter"].apply(
            self._normalize_quarter_value
        )
        shares_df["share_end_date"] = pd.to_datetime(
            shares_df["share_end_date"], errors="coerce"
        )
        shares_df["shares_outstanding"] = pd.to_numeric(
            shares_df["shares_outstanding"], errors="coerce"
        )
        shares_df = shares_df.dropna(subset=["fiscal_year", "fiscal_quarter"])
        shares_df = shares_df.sort_values("share_end_date")
        shares_df = shares_df.drop_duplicates(
            subset=["symbol", "fiscal_year", "fiscal_quarter"], keep="last"
        )
        return shares_df[
            ["symbol", "fiscal_year", "fiscal_quarter", "shares_outstanding"]
        ]

    @staticmethod
    def _normalize_quarter_value(value):
        """Normalize quarter representations to integer 1..4."""
        if value is None:
            return None
        text = str(value).strip().upper()
        mapping = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}
        if text in mapping:
            return mapping[text]
        try:
            q = int(float(text))
            return q if q in (1, 2, 3, 4) else None
        except (TypeError, ValueError):
            return None
