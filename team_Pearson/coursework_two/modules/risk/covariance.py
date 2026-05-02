from __future__ import annotations

"""Shared covariance and ex-ante portfolio risk utilities for CW2."""

import math
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional

import numpy as np
import pandas as pd

_ANNUALIZATION_FACTOR = 252.0
_STATISTICAL_FACTOR_COVARIANCE_METHODS = frozenset(
    {"statistical_factor", "factor_model", "pca_factor"}
)
_FUNDAMENTAL_FACTOR_COVARIANCE_METHODS = frozenset(
    {"fundamental_factor", "fundamental_factor_model", "barra_lite"}
)
_FACTOR_COVARIANCE_METHODS = (
    _STATISTICAL_FACTOR_COVARIANCE_METHODS | _FUNDAMENTAL_FACTOR_COVARIANCE_METHODS
)
_DEFAULT_FUNDAMENTAL_STYLE_FACTORS = (
    "market_beta",
    "size",
    "value",
    "momentum",
    "quality",
    "volatility",
    "liquidity",
    "dividend",
)


def is_factor_covariance_method(method: str) -> bool:
    """Return whether a covariance method uses any factor estimator."""
    return str(method or "").strip().lower() in _FACTOR_COVARIANCE_METHODS


def is_fundamental_covariance_method(method: str) -> bool:
    """Return whether a covariance method uses fundamental/style exposures."""
    return str(method or "").strip().lower() in _FUNDAMENTAL_FACTOR_COVARIANCE_METHODS


def is_statistical_factor_covariance_method(method: str) -> bool:
    """Return whether a covariance method uses the PCA/statistical estimator."""
    return str(method or "").strip().lower() in _STATISTICAL_FACTOR_COVARIANCE_METHODS


def covariance_method_label(method: str, shrinkage_intensity: float) -> str:
    """Build the persisted label for a covariance estimator."""
    method_name = str(method or "diagonal_shrinkage").strip().lower()
    if method_name == "diagonal_shrinkage":
        return f"diagonal_shrinkage_{float(shrinkage_intensity):.2f}"
    return method_name


def build_return_panel(
    price_panel: pd.DataFrame,
    *,
    trading_calendar: list[Any],
    start_date: Any,
    end_date: Any,
    lookback_days: int,
    min_history_days: int,
    max_forward_fill_days: int,
) -> pd.DataFrame:
    """Convert PIT-clean adjusted-close prices into a dense daily return panel."""
    if price_panel is None or price_panel.empty:
        return pd.DataFrame()

    window_calendar = [
        dt
        for dt in sorted({dt for dt in trading_calendar if dt is not None})
        if start_date <= dt <= end_date
    ]
    if len(window_calendar) < 3:
        return pd.DataFrame()

    panel = price_panel.copy()
    panel.index = pd.to_datetime(panel.index, errors="coerce").date
    panel = panel.reindex(window_calendar).sort_index()
    panel = panel.apply(pd.to_numeric, errors="coerce")
    observed = panel.notna()
    filled = panel.ffill(limit=max_forward_fill_days)
    imputed = observed.eq(False) & filled.notna()

    returns = filled.pct_change()
    returns = returns.mask(imputed | imputed.shift(1, fill_value=False)).dropna(how="all")
    if returns.empty:
        return pd.DataFrame()

    if len(returns) > lookback_days:
        returns = returns.tail(lookback_days)

    coverage = returns.notna().sum(axis=0)
    keep_cols = [col for col in returns.columns if int(coverage.get(col, 0)) >= min_history_days]
    if not keep_cols:
        return pd.DataFrame()

    return returns[keep_cols].dropna(how="all")


def estimate_shrunk_covariance(
    returns: pd.DataFrame,
    *,
    shrinkage_intensity: float,
    method: str = "diagonal_shrinkage",
    factor_count: Optional[int] = None,
    max_factor_count: int = 5,
    factor_variance_target: Optional[float] = None,
    specific_variance_floor_ratio: float = 0.05,
) -> pd.DataFrame:
    """Estimate a covariance matrix from daily returns using the requested shrinkage method."""
    if returns.empty or returns.shape[1] == 0:
        return pd.DataFrame()

    method_name = str(method or "diagonal_shrinkage").strip().lower()
    if is_statistical_factor_covariance_method(method_name):
        return estimate_statistical_factor_covariance(
            returns,
            factor_count=factor_count,
            max_factor_count=max_factor_count,
            factor_variance_target=factor_variance_target,
            specific_variance_floor_ratio=specific_variance_floor_ratio,
        )
    if is_fundamental_covariance_method(method_name):
        return pd.DataFrame()

    if method_name == "ledoit_wolf":
        complete = returns.dropna(axis=0, how="any")
        if complete.empty:
            return pd.DataFrame()
        try:
            from sklearn.covariance import LedoitWolf
        except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
            raise RuntimeError(
                "covariance.method='ledoit_wolf' requested, but scikit-learn is not installed"
            ) from exc
        estimator = LedoitWolf().fit(complete.to_numpy(dtype=float))
        return pd.DataFrame(
            estimator.covariance_,
            index=complete.columns,
            columns=complete.columns,
        )

    sample_cov = returns.cov()
    if sample_cov.empty:
        return pd.DataFrame()

    lam = min(max(float(shrinkage_intensity), 0.0), 1.0)
    diag_target = pd.DataFrame(
        np.diag(np.diag(sample_cov.to_numpy(dtype=float))),
        index=sample_cov.index,
        columns=sample_cov.columns,
    )
    return (1.0 - lam) * sample_cov + lam * diag_target


def estimate_statistical_factor_covariance(
    returns: pd.DataFrame,
    *,
    factor_count: Optional[int] = None,
    max_factor_count: int = 5,
    factor_variance_target: Optional[float] = None,
    specific_variance_floor_ratio: float = 0.05,
) -> pd.DataFrame:
    """Estimate a PCA-style factor covariance matrix from PIT daily returns.

    The estimator decomposes the sample covariance into a low-rank systematic
    component plus diagonal specific risk: ``Sigma = B F B' + D``. It uses only
    the supplied return history, so callers remain responsible for providing a
    point-in-time return panel.
    """
    if returns.empty or returns.shape[1] == 0:
        return pd.DataFrame()

    clean = returns.apply(pd.to_numeric, errors="coerce").dropna(axis=1, how="all")
    if clean.empty:
        return pd.DataFrame()

    coverage = clean.notna().sum(axis=0)
    clean = clean.loc[:, coverage >= 2]
    if clean.empty:
        return pd.DataFrame()

    column_means = clean.mean(axis=0, skipna=True)
    centered = clean.subtract(column_means, axis=1).fillna(0.0)
    if centered.shape[0] < 2 or centered.shape[1] == 0:
        return pd.DataFrame()

    sample_cov = clean.cov().reindex(index=centered.columns, columns=centered.columns)
    if sample_cov.empty:
        return pd.DataFrame()
    sample_cov = sample_cov.fillna(0.0)
    sample_matrix = 0.5 * (sample_cov.to_numpy(dtype=float) + sample_cov.to_numpy(dtype=float).T)
    if not np.isfinite(sample_matrix).all():
        return pd.DataFrame()

    eigenvalues, eigenvectors = np.linalg.eigh(sample_matrix)
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = np.clip(eigenvalues[order], 0.0, None)
    eigenvectors = eigenvectors[:, order]

    positive_count = int(np.sum(eigenvalues > 0.0))
    if positive_count == 0:
        diag = np.diag(np.clip(np.diag(sample_matrix), 0.0, None))
        return pd.DataFrame(diag, index=sample_cov.index, columns=sample_cov.columns)

    max_k = max(1, min(int(max_factor_count), positive_count, centered.shape[1]))
    if factor_count is not None:
        k = max(1, min(int(factor_count), max_k))
    elif factor_variance_target is not None:
        target = min(max(float(factor_variance_target), 0.0), 1.0)
        explained = np.cumsum(eigenvalues[:positive_count]) / float(
            np.sum(eigenvalues[:positive_count])
        )
        k = int(np.searchsorted(explained, target, side="left") + 1)
        k = max(1, min(k, max_k))
    else:
        k = max_k

    loadings = eigenvectors[:, :k]
    factor_values = eigenvalues[:k]
    factor_cov = (loadings * factor_values) @ loadings.T

    residual_diag = np.diag(sample_matrix - factor_cov)
    sample_diag = np.clip(np.diag(sample_matrix), 0.0, None)
    positive_diag = sample_diag[sample_diag > 0.0]
    median_variance = float(np.median(positive_diag)) if positive_diag.size else 0.0
    specific_floor = max(0.0, float(specific_variance_floor_ratio)) * median_variance
    specific_diag = np.maximum(residual_diag, specific_floor)

    factor_model_cov = factor_cov + np.diag(specific_diag)
    factor_model_cov = 0.5 * (factor_model_cov + factor_model_cov.T)
    return pd.DataFrame(
        factor_model_cov,
        index=sample_cov.index,
        columns=sample_cov.columns,
    )


def estimate_fundamental_factor_covariance(
    returns: pd.DataFrame,
    exposure_observations: pd.DataFrame,
    *,
    sector_map: Optional[Mapping[str, str]] = None,
    style_factors: Optional[Iterable[str]] = None,
    include_sector_factors: bool = True,
    exposure_lag_days: int = 1,
    max_exposure_staleness_days: int = 540,
    min_cross_section: int = 8,
    min_factor_return_days: int = 40,
    min_sector_members: int = 2,
    factor_ridge: float = 1.0e-4,
    factor_cov_shrinkage: float = 0.10,
    specific_variance_floor_ratio: float = 0.05,
    return_metadata: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, Dict[str, Any]]:
    """Estimate a Barra-style lite fundamental factor covariance matrix.

    The model builds point-in-time style and sector exposures, estimates daily
    factor returns by cross-sectional ridge regression, and reconstructs asset
    covariance as ``Sigma = X F X' + D``.
    """
    empty_result: pd.DataFrame | tuple[pd.DataFrame, Dict[str, Any]]
    empty_meta: Dict[str, Any] = {
        "factor_return_days": 0,
        "fundamental_factor_names": [],
        "fundamental_sector_factor_count": 0,
        "fundamental_style_factor_count": 0,
        "specific_risk_method": "residual_variance",
    }
    empty_result = (pd.DataFrame(), empty_meta) if return_metadata else pd.DataFrame()
    if returns is None or returns.empty or returns.shape[1] == 0:
        return empty_result
    if exposure_observations is None or exposure_observations.empty:
        return empty_result

    returns_clean = returns.apply(pd.to_numeric, errors="coerce").dropna(how="all")
    returns_clean = returns_clean.dropna(axis=1, how="all")
    if returns_clean.empty:
        return empty_result

    parsed_index = pd.to_datetime(returns_clean.index, errors="coerce")
    valid_date_mask = pd.notna(parsed_index)
    if not bool(valid_date_mask.any()):
        return empty_result
    returns_clean = returns_clean.loc[valid_date_mask].copy()
    returns_clean.index = parsed_index[valid_date_mask].date
    returns_clean = returns_clean.sort_index()

    symbols = [str(col) for col in returns_clean.columns]
    exposure_panel = _prepare_exposure_panel(
        exposure_observations,
        symbols=symbols,
        return_dates=list(returns_clean.index),
        exposure_lag_days=exposure_lag_days,
        max_exposure_staleness_days=max_exposure_staleness_days,
    )
    if not exposure_panel:
        return empty_result

    current_date = list(returns_clean.index)[-1]
    current_raw = exposure_panel.get(current_date)
    if current_raw is None or current_raw.empty:
        return empty_result

    current_x, factor_names, sector_factor_names, style_factor_names = (
        _build_fundamental_exposure_matrix(
            current_raw,
            symbols=symbols,
            sector_map=sector_map or {},
            style_factors=style_factors,
            include_sector_factors=include_sector_factors,
            min_sector_members=min_sector_members,
            fixed_factor_names=None,
        )
    )
    if current_x.empty or not factor_names:
        return empty_result

    factor_return_rows: List[pd.Series] = []
    residual_rows: List[pd.Series] = []
    min_names = max(3, int(min_cross_section))
    for ret_date, ret_row in returns_clean.iterrows():
        raw_x = exposure_panel.get(ret_date)
        if raw_x is None or raw_x.empty:
            continue
        valid_symbols = [
            sym for sym in symbols if sym in ret_row.index and pd.notna(ret_row.get(sym))
        ]
        if len(valid_symbols) < min_names:
            continue
        x_t, _, _, _ = _build_fundamental_exposure_matrix(
            raw_x,
            symbols=valid_symbols,
            sector_map=sector_map or {},
            style_factors=style_factor_names,
            include_sector_factors=include_sector_factors,
            min_sector_members=min_sector_members,
            fixed_factor_names=factor_names,
        )
        if x_t.empty:
            continue
        aligned_symbols = [sym for sym in valid_symbols if sym in x_t.index]
        if len(aligned_symbols) < min_names:
            continue
        y = ret_row.reindex(aligned_symbols).to_numpy(dtype=float)
        x = x_t.reindex(index=aligned_symbols, columns=factor_names).to_numpy(dtype=float)
        if not np.isfinite(y).all() or not np.isfinite(x).all():
            continue
        coef = _solve_ridge_factor_return(x, y, ridge=float(factor_ridge))
        fitted = x @ coef
        residual = y - fitted
        factor_return_rows.append(pd.Series(coef, index=factor_names, name=ret_date))
        residual_rows.append(pd.Series(residual, index=aligned_symbols, name=ret_date, dtype=float))

    if len(factor_return_rows) < int(min_factor_return_days):
        meta = {
            **empty_meta,
            "factor_return_days": len(factor_return_rows),
            "fundamental_factor_names": factor_names,
            "fundamental_sector_factor_count": len(sector_factor_names),
            "fundamental_style_factor_count": len(style_factor_names),
            "covariance_reason": "insufficient_factor_return_days",
        }
        return (pd.DataFrame(), meta) if return_metadata else pd.DataFrame()

    factor_returns = pd.DataFrame(factor_return_rows).sort_index()
    factor_cov = factor_returns.cov().reindex(index=factor_names, columns=factor_names)
    factor_cov = factor_cov.fillna(0.0)
    factor_cov_matrix = 0.5 * (
        factor_cov.to_numpy(dtype=float) + factor_cov.to_numpy(dtype=float).T
    )
    if float(factor_cov_shrinkage) > 0.0:
        lam = min(max(float(factor_cov_shrinkage), 0.0), 1.0)
        factor_cov_matrix = (1.0 - lam) * factor_cov_matrix + lam * np.diag(
            np.diag(factor_cov_matrix)
        )

    residuals = pd.DataFrame(residual_rows).sort_index()
    sample_var = returns_clean.var(axis=0, skipna=True).reindex(symbols)
    specific_var = residuals.var(axis=0, skipna=True).reindex(symbols)
    specific_var = specific_var.where(specific_var > 0.0, sample_var)
    positive_sample_var = sample_var[sample_var > 0.0].dropna()
    median_sample_var = (
        float(positive_sample_var.median()) if not positive_sample_var.empty else 0.0
    )
    specific_floor = max(0.0, float(specific_variance_floor_ratio)) * median_sample_var
    specific_var = specific_var.fillna(median_sample_var).clip(lower=specific_floor)

    x_current = current_x.reindex(index=symbols, columns=factor_names).fillna(0.0)
    cov_matrix = x_current.to_numpy(dtype=float) @ factor_cov_matrix @ x_current.to_numpy(
        dtype=float
    ).T + np.diag(specific_var.reindex(symbols).to_numpy(dtype=float))
    cov_matrix = 0.5 * (cov_matrix + cov_matrix.T)
    covariance = pd.DataFrame(cov_matrix, index=symbols, columns=symbols)
    meta = {
        "factor_return_days": int(len(factor_returns)),
        "fundamental_factor_names": list(factor_names),
        "fundamental_sector_factor_count": int(len(sector_factor_names)),
        "fundamental_style_factor_count": int(len(style_factor_names)),
        "specific_risk_method": "residual_variance",
        "factor_cov_shrinkage": float(factor_cov_shrinkage),
        "factor_ridge": float(factor_ridge),
        "exposure_lag_days": int(exposure_lag_days),
        "max_exposure_staleness_days": int(max_exposure_staleness_days),
    }
    return (covariance, meta) if return_metadata else covariance


def _prepare_exposure_panel(
    exposure_observations: pd.DataFrame,
    *,
    symbols: list[str],
    return_dates: list[Any],
    exposure_lag_days: int,
    max_exposure_staleness_days: int,
) -> Dict[Any, pd.DataFrame]:
    exposures = exposure_observations.copy()
    date_col = "as_of_date" if "as_of_date" in exposures.columns else "effective_date"
    if date_col not in exposures.columns or "symbol" not in exposures.columns:
        return {}

    exposures[date_col] = pd.to_datetime(exposures[date_col], errors="coerce").dt.date
    exposures["symbol"] = exposures["symbol"].astype(str)
    exposures = exposures[exposures[date_col].notna() & exposures["symbol"].isin(symbols)].copy()
    if exposures.empty:
        return {}

    if {"factor_name", "factor_value"}.issubset(exposures.columns):
        index_cols = [date_col, "symbol"]
        if "gics_sector" in exposures.columns:
            index_cols.append("gics_sector")
        exposures = (
            exposures.pivot_table(
                index=index_cols,
                columns="factor_name",
                values="factor_value",
                aggfunc="last",
            )
            .reset_index()
            .rename_axis(columns=None)
        )

    numeric_cols = [
        col
        for col in exposures.columns
        if col not in {date_col, "symbol", "gics_sector", "observation_date"}
    ]
    for col in numeric_cols:
        exposures[col] = pd.to_numeric(exposures[col], errors="coerce")
    exposures = exposures.sort_values([date_col, "symbol"])

    allowed_dates = [
        (pd.Timestamp(dt) - pd.Timedelta(days=int(exposure_lag_days))).date() for dt in return_dates
    ]
    out: Dict[Any, pd.DataFrame] = {}
    max_stale = max(0, int(max_exposure_staleness_days))
    for symbol in symbols:
        sym_rows = exposures[exposures["symbol"] == symbol].copy()
        if sym_rows.empty:
            continue
        sym_rows = sym_rows.sort_values(date_col).drop_duplicates(subset=[date_col], keep="last")
        sym_rows = sym_rows.set_index(date_col)
        combined_index = sorted(set(sym_rows.index).union(allowed_dates))
        dense = sym_rows.reindex(combined_index).ffill()
        for ret_date, allowed_date in zip(return_dates, allowed_dates):
            if allowed_date not in dense.index:
                continue
            row = dense.loc[allowed_date].copy()
            if row.drop(labels=["symbol"], errors="ignore").isna().all():
                continue
            latest_source_date = max(
                [idx for idx in sym_rows.index if idx <= allowed_date], default=None
            )
            if latest_source_date is None:
                continue
            if (allowed_date - latest_source_date).days > max_stale:
                continue
            row["symbol"] = symbol
            out.setdefault(ret_date, []).append(row)

    return {dt: pd.DataFrame(rows).reset_index(drop=True) for dt, rows in out.items() if rows}


def _build_fundamental_exposure_matrix(
    raw_exposures: pd.DataFrame,
    *,
    symbols: list[str],
    sector_map: Mapping[str, str],
    style_factors: Optional[Iterable[str]],
    include_sector_factors: bool,
    min_sector_members: int,
    fixed_factor_names: Optional[list[str]],
) -> tuple[pd.DataFrame, list[str], list[str], list[str]]:
    raw = raw_exposures.copy()
    if raw.empty or "symbol" not in raw.columns:
        return pd.DataFrame(), [], [], []
    raw["symbol"] = raw["symbol"].astype(str)
    raw = raw[raw["symbol"].isin(symbols)].drop_duplicates("symbol", keep="last")
    raw = raw.set_index("symbol", drop=False)
    if raw.empty:
        return pd.DataFrame(), [], [], []

    style = _derive_fundamental_style_factors(raw)
    requested_styles = [
        str(name).strip()
        for name in (style_factors or _DEFAULT_FUNDAMENTAL_STYLE_FACTORS)
        if str(name).strip()
    ]
    style_cols = [name for name in requested_styles if name in style.columns]
    style = style.reindex(index=raw.index, columns=style_cols).fillna(0.0)

    sector = pd.Series(
        {
            sym: str(raw.loc[sym].get("gics_sector") or sector_map.get(sym) or "Unknown")
            for sym in raw.index
        }
    )
    sector_cols: list[str] = []
    sector_frame = pd.DataFrame(index=raw.index)
    if include_sector_factors:
        sector_counts = sector.value_counts()
        eligible_sectors = [
            sec
            for sec, count in sector_counts.items()
            if sec and sec != "Unknown" and int(count) >= int(min_sector_members)
        ]
        for sec in sorted(eligible_sectors):
            col = f"sector:{sec}"
            sector_frame[col] = (sector == sec).astype(float)
            sector_cols.append(col)

    x = pd.concat([style, sector_frame], axis=1).fillna(0.0)
    if fixed_factor_names is not None:
        factor_names = list(fixed_factor_names)
        x = x.reindex(columns=factor_names, fill_value=0.0)
        sector_cols = [name for name in factor_names if name.startswith("sector:")]
        style_cols = [name for name in factor_names if not name.startswith("sector:")]
    else:
        factor_names = list(style.columns) + sector_cols
        x = x.reindex(columns=factor_names, fill_value=0.0)
    x = x.reindex(index=symbols).dropna(how="all")
    return x, factor_names, sector_cols, style_cols


def _derive_fundamental_style_factors(raw: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=raw.index)
    if "beta_1y" in raw.columns:
        beta = pd.to_numeric(raw["beta_1y"], errors="coerce")
        out["market_beta"] = beta.fillna(beta.median() if beta.notna().any() else 1.0)

    out["size"] = _zscore_or_zero(_numeric_col(raw, "log_market_cap"))
    value_inputs = [
        _zscore_or_zero(_numeric_col(raw, "book_to_price")),
        _zscore_or_zero(_safe_inverse(_numeric_col(raw, "pb_ratio"))),
        _zscore_or_zero(_numeric_col(raw, "earnings_to_price")),
        _zscore_or_zero(_numeric_col(raw, "ep_ratio")),
        _zscore_or_zero(_numeric_col(raw, "ebitda_to_ev")),
        _zscore_or_zero(_numeric_col(raw, "value_score")),
    ]
    out["value"] = _combine_factor_inputs(value_inputs)

    momentum_inputs = [
        _zscore_or_zero(_numeric_col(raw, "momentum_12m")),
        _zscore_or_zero(_numeric_col(raw, "momentum_12_1m")),
        _zscore_or_zero(_numeric_col(raw, "momentum_6m")),
        _zscore_or_zero(_numeric_col(raw, "momentum_3m")),
        _zscore_or_zero(_numeric_col(raw, "momentum_1m")),
        _zscore_or_zero(_numeric_col(raw, "market_technical_score")),
    ]
    out["momentum"] = _combine_factor_inputs(momentum_inputs)

    quality_inputs = [
        _zscore_or_zero(_numeric_col(raw, "ebitda_margin")),
        _zscore_or_zero(_numeric_col(raw, "roe")),
        _zscore_or_zero(_numeric_col(raw, "debt_to_equity_inv")),
        _zscore_or_zero(-_numeric_col(raw, "debt_to_equity")),
        _zscore_or_zero(_numeric_col(raw, "quality_score")),
    ]
    out["quality"] = _combine_factor_inputs(quality_inputs)
    volatility = _numeric_col(raw, "volatility_60d")
    if not volatility.notna().any():
        volatility = _numeric_col(raw, "volatility_20d")
    out["volatility"] = _zscore_or_zero(volatility)
    liquidity = _numeric_col(raw, "liquidity_20d").clip(lower=0.0)
    out["liquidity"] = _zscore_or_zero(np.log1p(liquidity))
    dividend_inputs = [
        _zscore_or_zero(_numeric_col(raw, "dividend_yield")),
        _zscore_or_zero(_numeric_col(raw, "dividend_stability")),
        _zscore_or_zero(_numeric_col(raw, "payout_sustainability")),
        _zscore_or_zero(-_numeric_col(raw, "payout_ratio")),
        _zscore_or_zero(_numeric_col(raw, "dividend_score")),
    ]
    out["dividend"] = _combine_factor_inputs(dividend_inputs)
    return out.fillna(0.0)


def _numeric_col(raw: pd.DataFrame, col: str) -> pd.Series:
    if col not in raw.columns:
        return pd.Series(np.nan, index=raw.index, dtype=float)
    return pd.to_numeric(raw[col], errors="coerce").astype(float)


def _safe_inverse(series: pd.Series) -> pd.Series:
    clean = pd.to_numeric(series, errors="coerce")
    return pd.Series(
        np.divide(1.0, clean, out=np.full(len(clean), np.nan), where=clean > 0.0),
        index=series.index,
        dtype=float,
    )


def _zscore_or_zero(series: pd.Series | np.ndarray) -> pd.Series:
    if isinstance(series, pd.Series):
        s = pd.to_numeric(series, errors="coerce").astype(float)
    else:
        s = pd.Series(series, dtype=float)
    valid = s.replace([np.inf, -np.inf], np.nan).dropna()
    if len(valid) < 2:
        return pd.Series(0.0, index=s.index, dtype=float)
    mean = float(valid.mean())
    std = float(valid.std(ddof=1))
    if std <= 0.0 or not np.isfinite(std):
        return pd.Series(0.0, index=s.index, dtype=float)
    return ((s - mean) / std).replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _combine_factor_inputs(inputs: list[pd.Series]) -> pd.Series:
    usable = [
        series
        for series in inputs
        if series is not None and float(series.abs().sum(skipna=True)) > 0.0
    ]
    if not usable:
        index = inputs[0].index if inputs else pd.Index([])
        return pd.Series(0.0, index=index, dtype=float)
    return pd.concat(usable, axis=1).mean(axis=1).fillna(0.0)


def _solve_ridge_factor_return(x: np.ndarray, y: np.ndarray, *, ridge: float) -> np.ndarray:
    if x.size == 0:
        return np.zeros(0, dtype=float)
    xtx = x.T @ x
    p = xtx.shape[0]
    scale = float(np.trace(xtx) / max(1, p))
    penalty = max(float(ridge), 0.0) * (scale if scale > 0.0 else 1.0)
    rhs = x.T @ y
    try:
        return np.linalg.solve(xtx + np.eye(p) * penalty, rhs)
    except np.linalg.LinAlgError:
        return np.linalg.pinv(xtx + np.eye(p) * penalty) @ rhs


def covariance_quality(
    covariance: pd.DataFrame,
    *,
    max_condition_number: float = 1e8,
    relative_eigen_floor: float = 1e-10,
    absolute_eigen_floor: float = 1e-12,
) -> Dict[str, Any]:
    """Assess whether a covariance matrix is numerically usable."""
    if covariance.empty or covariance.shape[0] == 0:
        return {
            "is_usable": False,
            "reason": "empty",
            "condition_number": math.inf,
            "min_eigenvalue": None,
            "max_eigenvalue": None,
        }

    matrix = covariance.to_numpy(dtype=float)
    if not np.isfinite(matrix).all():
        return {
            "is_usable": False,
            "reason": "non_finite",
            "condition_number": math.inf,
            "min_eigenvalue": None,
            "max_eigenvalue": None,
        }

    symmetric = 0.5 * (matrix + matrix.T)
    eigenvalues = np.linalg.eigvalsh(symmetric)
    max_eigenvalue = float(np.max(eigenvalues))
    min_eigenvalue = float(np.min(eigenvalues))
    eigen_floor = max(
        float(absolute_eigen_floor), abs(max_eigenvalue) * float(relative_eigen_floor)
    )

    if max_eigenvalue <= eigen_floor:
        return {
            "is_usable": False,
            "reason": "near_zero_variance",
            "condition_number": math.inf,
            "min_eigenvalue": min_eigenvalue,
            "max_eigenvalue": max_eigenvalue,
        }

    if min_eigenvalue <= eigen_floor:
        return {
            "is_usable": False,
            "reason": "near_singular",
            "condition_number": math.inf,
            "min_eigenvalue": min_eigenvalue,
            "max_eigenvalue": max_eigenvalue,
        }

    condition_number = float(max_eigenvalue / min_eigenvalue)
    if condition_number > float(max_condition_number):
        return {
            "is_usable": False,
            "reason": "ill_conditioned",
            "condition_number": condition_number,
            "min_eigenvalue": min_eigenvalue,
            "max_eigenvalue": max_eigenvalue,
        }

    return {
        "is_usable": True,
        "reason": "ok",
        "condition_number": condition_number,
        "min_eigenvalue": min_eigenvalue,
        "max_eigenvalue": max_eigenvalue,
    }


def normalize_weights(weights: Mapping[str, float]) -> Dict[str, float]:
    clean = {str(sym): float(w) for sym, w in weights.items() if float(w) > 0}
    total = sum(clean.values())
    if total <= 0:
        return {}
    return {sym: w / total for sym, w in clean.items()}


def align_weights(weights: Mapping[str, float], symbols: Iterable[str]) -> Dict[str, float]:
    aligned = {
        str(sym): float(weights.get(sym, 0.0))
        for sym in symbols
        if float(weights.get(sym, 0.0)) > 0
    }
    return normalize_weights(aligned)


def ex_ante_tracking_error(
    weights: Mapping[str, float],
    benchmark_weights: Mapping[str, float],
    covariance: pd.DataFrame,
) -> Optional[float]:
    """Annualized ex-ante tracking error under a covariance model."""
    universe = list(covariance.columns)
    active = np.array(
        [float(weights.get(sym, 0.0)) - float(benchmark_weights.get(sym, 0.0)) for sym in universe],
        dtype=float,
    )
    cov = covariance.to_numpy(dtype=float)
    active_var = float(active @ cov @ active)
    if active_var < 0:
        return None
    return float(np.sqrt(active_var) * np.sqrt(_ANNUALIZATION_FACTOR))


def portfolio_risk_stats(
    weights: Mapping[str, float],
    covariance: pd.DataFrame,
    sector_map: Mapping[str, str],
) -> Dict[str, Any]:
    """Compute ex-ante volatility, diversification, and risk-contribution diagnostics."""
    ordered = [str(col) for col in covariance.columns if str(col) in weights]
    if not ordered:
        return {}

    w = np.array([float(weights[sym]) for sym in ordered], dtype=float)
    cov = covariance.loc[ordered, ordered].to_numpy(dtype=float)
    port_var = float(w @ cov @ w)
    if port_var <= 0:
        return {}

    port_vol = float(np.sqrt(port_var))
    annualized_vol = port_vol * float(np.sqrt(_ANNUALIZATION_FACTOR))
    marginal = cov @ w
    component_var = w * marginal
    frac = component_var / port_var
    component_vol_ann = frac * annualized_vol

    indiv_vol = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    weighted_vol_sum = float(np.dot(w, indiv_vol))
    diversification_ratio = None if port_vol <= 0 else weighted_vol_sum / port_vol

    effective_risk_bets = None
    frac_positive = np.clip(frac, 0.0, None)
    frac_positive_sum = float(frac_positive.sum())
    if frac_positive_sum > 0:
        frac_norm = frac_positive / frac_positive_sum
        effective_risk_bets = 1.0 / float(np.square(frac_norm).sum())

    avg_pairwise_corr = weighted_average_pairwise_correlation(w, cov)

    asset_rows = []
    sector_contrib: Dict[str, float] = defaultdict(float)
    sector_weight: Dict[str, float] = defaultdict(float)
    for idx, symbol in enumerate(ordered):
        sector = str(sector_map.get(symbol) or "Unknown")
        risk_share = float(frac[idx])
        sector_contrib[sector] += risk_share
        sector_weight[sector] += float(w[idx])
        asset_rows.append(
            {
                "dimension_type": "asset",
                "dimension_name": symbol,
                "portfolio_weight": float(w[idx]),
                "risk_contribution_pct": risk_share * 100.0,
                "component_volatility_contribution": float(component_vol_ann[idx]) * 100.0,
            }
        )

    sector_rows = [
        {
            "dimension_type": "sector",
            "dimension_name": sector,
            "portfolio_weight": float(sector_weight[sector]),
            "risk_contribution_pct": float(contrib) * 100.0,
            "component_volatility_contribution": float(contrib * annualized_vol) * 100.0,
        }
        for sector, contrib in sector_contrib.items()
    ]

    top_asset_risk_share = max((row["risk_contribution_pct"] for row in asset_rows), default=None)
    top_sector_risk_share = max((row["risk_contribution_pct"] for row in sector_rows), default=None)

    return {
        "n_assets": len(ordered),
        "annualized_volatility": annualized_vol,
        "diversification_ratio": diversification_ratio,
        "effective_risk_bets": effective_risk_bets,
        "avg_pairwise_correlation": avg_pairwise_corr,
        "top_asset_risk_share": (
            None if top_asset_risk_share is None else top_asset_risk_share / 100.0
        ),
        "top_sector_risk_share": (
            None if top_sector_risk_share is None else top_sector_risk_share / 100.0
        ),
        "asset_contributions": asset_rows,
        "sector_contributions": sector_rows,
    }


def weighted_average_pairwise_correlation(
    weights: np.ndarray, covariance: np.ndarray
) -> Optional[float]:
    """Weighted average off-diagonal correlation implied by a covariance matrix."""
    if len(weights) < 2:
        return None

    vols = np.sqrt(np.clip(np.diag(covariance), 0.0, None))
    denom = np.outer(vols, vols)
    corr = np.divide(covariance, denom, out=np.zeros_like(covariance), where=denom > 0)
    pair_weight_sum = 0.0
    weighted_corr_sum = 0.0

    for i in range(len(weights)):
        for j in range(i + 1, len(weights)):
            pair_w = float(weights[i] * weights[j])
            pair_weight_sum += pair_w
            weighted_corr_sum += pair_w * float(corr[i, j])

    if pair_weight_sum <= 0:
        return None
    return weighted_corr_sum / pair_weight_sum


def lookback_start(
    trading_calendar: list[Any],
    rebalance_date: Any,
    lookback_days: int,
    max_forward_fill_days: int,
) -> Any:
    """Return a calendar start date that includes enough buffer for forward fills."""
    ordered = sorted({dt for dt in trading_calendar if dt is not None})
    idx = ordered.index(rebalance_date) if rebalance_date in ordered else len(ordered) - 1
    start_idx = max(0, idx - (lookback_days + max_forward_fill_days + 1))
    return ordered[start_idx]


__all__ = [
    "align_weights",
    "build_return_panel",
    "covariance_method_label",
    "covariance_quality",
    "estimate_fundamental_factor_covariance",
    "estimate_shrunk_covariance",
    "estimate_statistical_factor_covariance",
    "ex_ante_tracking_error",
    "is_factor_covariance_method",
    "is_fundamental_covariance_method",
    "is_statistical_factor_covariance_method",
    "lookback_start",
    "normalize_weights",
    "portfolio_risk_stats",
    "weighted_average_pairwise_correlation",
]
