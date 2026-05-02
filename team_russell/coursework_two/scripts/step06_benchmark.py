"""Step 06 — Benchmark Comparison: Q1 vs S&P 500, MSCI World, MSCI ACWI, EW Universe.

Adds proper market index benchmarks alongside the internal equal-weighted universe
benchmark used in earlier steps.

Benchmarks:
  SPY   — S&P 500 (US large-cap only, market-cap weighted)
  URTH  — MSCI World (developed markets, market-cap weighted)
  ACWI  — MSCI All Country World Index (developed + emerging, market-cap weighted)
  EW    — Equal-weighted universe (internal benchmark, same as steps 5–11)

For each quarterly holding period:
  Index return = (P_end / P_start) - 1  (gross, price return only, no dividends)
  Net return   = gross - 0.004 (same 0.4% transaction cost for fair comparison)

Outputs:
  results/benchmark_comparison.csv
  results/charts/04_benchmark_comparison.png
  results/charts/05_benchmark_alpha.png

Usage:
    cd team_russell/coursework_one
    poetry run python ../coursework_two/scripts/step06_benchmark.py
"""

import sys
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns
import yfinance as yf
from scipy import stats as scipy_stats

sys.path.insert(0, str(Path(__file__).parent))
from _table_utils import save_table_png

warnings.filterwarnings("ignore")

BASE = Path(__file__).parent.parent
RESULTS = BASE / "results"
CHARTS = RESULTS / "charts"
CHARTS.mkdir(parents=True, exist_ok=True)

TC_RT = 0.004

from _rf_rates import rf_quarterly_series  # noqa: E402

BENCHMARKS = {
    "SPY": "S&P 500",
    "URTH": "MSCI World",
    "ACWI": "MSCI ACWI",
}

sns.set_theme(style="whitegrid", palette="muted", font_scale=1.05)


# ── Download index prices ─────────────────────────────────────────────────────
def download_index_prices() -> dict:  # pragma: no cover
    """Download daily close prices for all benchmark indices."""
    print("Downloading index prices...")
    prices = {}
    for ticker in BENCHMARKS:
        hist = yf.Ticker(ticker).history(start="2015-10-01", end="2026-01-05", auto_adjust=True)
        if not hist.empty:
            series = hist["Close"]
            series.index = series.index.tz_localize(None)  # strip timezone
            prices[ticker] = series
            print(f"  {ticker}: {len(hist)} days")
    return prices


def index_return(series: pd.Series, start_date: str, end_date: str) -> float:
    """Compute holding-period return between two dates (price on or nearest)."""
    s = pd.Timestamp(start_date)
    e = pd.Timestamp(end_date)

    before_s = series[series.index <= s]
    after_e = series[series.index >= e]

    if before_s.empty or after_e.empty:
        return np.nan

    p_start = float(before_s.iloc[-1])
    p_end = float(after_e.iloc[0])
    return (p_end - p_start) / p_start


# ── Load Q1 returns ───────────────────────────────────────────────────────────
def load_q1_returns() -> pd.DataFrame:  # pragma: no cover
    stock = pd.read_csv(RESULTS / "stock_returns_10year.csv")
    stock["start_date"] = pd.to_datetime(stock["start_date"])
    stock["end_date"] = pd.to_datetime(stock["end_date"])

    rows = []
    for (s, e), grp in stock.groupby(["start_date", "end_date"]):
        q1 = grp[grp["quintile"] == 1]
        bm = grp  # all stocks = EW universe
        if q1.empty:
            continue
        rows.append(
            {
                "start_date": s,
                "end_date": e,
                "q1_gross": q1["gross_return"].mean(),
                "q1_net": q1["gross_return"].mean() - TC_RT,
                "ew_gross": bm["gross_return"].mean(),
                "ew_net": bm["gross_return"].mean() - TC_RT,
            }
        )
    return pd.DataFrame(rows).sort_values("start_date").reset_index(drop=True)


# ── Build comparison table ────────────────────────────────────────────────────
def build_comparison(q1_df: pd.DataFrame, index_prices: dict) -> pd.DataFrame:
    rows = []
    for _, r in q1_df.iterrows():
        s = r["start_date"].strftime("%Y-%m-%d")
        e = r["end_date"].strftime("%Y-%m-%d")

        row = {
            "start_date": r["start_date"],
            "end_date": r["end_date"],
            "q1_net": r["q1_net"],
            "ew_net": r["ew_net"],
        }

        for ticker in BENCHMARKS:
            if ticker in index_prices:
                gross = index_return(index_prices[ticker], s, e)
                row[f"{ticker}_gross"] = gross
                row[f"{ticker}_net"] = gross - TC_RT if not np.isnan(gross) else np.nan

        rows.append(row)

    return pd.DataFrame(rows)


# ── Summary stats ─────────────────────────────────────────────────────────────
def jensen_alpha(
    portfolio: pd.Series,
    benchmark: pd.Series,
    rf_q: pd.Series,
) -> dict:
    """Compute Jensen's Alpha via OLS regression of excess returns.

    Model: (R_p - Rf) = α + β(R_m - Rf) + ε

    Alpha is the CAPM intercept — return unexplained by market exposure.
    Beta measures sensitivity to the benchmark.
    Both portfolio and benchmark must be quarterly net returns (same index).

    Parameters
    ----------
    portfolio, benchmark : quarterly net-return series (same length, pre-aligned).
    rf_q : quarterly T-bill rates aligned to portfolio/benchmark (same length).

    Returns alpha annualised as (1 + α_quarterly)^4 - 1.
    """
    # Align series and drop any periods where either is NaN
    df = pd.DataFrame({"rp": portfolio, "rm": benchmark}).dropna()
    if len(df) < 4:
        return {
            "alpha": np.nan,
            "beta": np.nan,
            "t_alpha": np.nan,
            "p_alpha": np.nan,
            "r_squared": np.nan,
        }

    rf_q_vals = np.asarray(rf_q)[: len(df)]
    y = df["rp"].values - rf_q_vals  # portfolio excess return (quarterly)
    x = df["rm"].values - rf_q_vals  # benchmark excess return (quarterly)

    slope, intercept, r, p_r, _ = scipy_stats.linregress(x, y)
    n = len(y)
    se = np.sqrt(((y - (intercept + slope * x)) ** 2).sum() / (n - 2) / ((x - x.mean()) ** 2).sum())
    t_alpha = intercept / se if se > 0 else np.nan
    p_alpha = 2 * scipy_stats.t.sf(abs(t_alpha), df=n - 2) if not np.isnan(t_alpha) else np.nan

    alpha_annual = (1 + intercept) ** 4 - 1

    return {
        "alpha": alpha_annual,
        "beta": slope,
        "t_alpha": t_alpha,
        "p_alpha": p_alpha,
        "r_squared": r**2,
    }


def ann_stats(series: pd.Series, rf_q: pd.Series) -> dict:
    """Annualised performance statistics.

    Parameters
    ----------
    series : quarterly net-return series
    rf_q   : quarterly T-bill rates aligned to series (same length)
    """
    avg = series.mean()
    std = series.std(ddof=1)
    ann_ret = (1 + avg) ** 4 - 1
    ann_vol = std * np.sqrt(4)
    excess = np.asarray(series) - np.asarray(rf_q)
    ann_excess = float(np.mean(excess)) * 4
    sharpe = ann_excess / ann_vol if ann_vol > 0 else np.nan
    downside = np.minimum(excess, 0)
    down_dev = np.sqrt(np.mean(downside**2)) * np.sqrt(4) if np.any(downside < 0) else 0.0
    sortino = ann_excess / down_dev if down_dev > 0 else np.nan
    cum = (1 + series).prod() - 1
    return {
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "cum": cum,
    }


# ── Charts ────────────────────────────────────────────────────────────────────
def chart_nav_comparison(comp_df: pd.DataFrame):  # pragma: no cover
    """Cumulative NAV for Q1, EW, and all index benchmarks."""
    fig, ax = plt.subplots(figsize=(13, 6))

    colors = {
        "q1_net": ("#2166ac", "Q1 Strategy", 2.5, "-"),
        "ew_net": ("black", "EW Universe", 1.5, ":"),
        "SPY_net": ("#d73027", "S&P 500 (SPY)", 1.8, "--"),
        "URTH_net": ("#4dac26", "MSCI World (URTH)", 1.8, "-."),
        "ACWI_net": ("#7b3294", "MSCI ACWI (ACWI)", 1.8, (0, (3, 1, 1, 1))),
    }

    dates = [comp_df["start_date"].iloc[0]] + list(comp_df["end_date"])

    for col, (color, label, lw, ls) in colors.items():
        if col not in comp_df.columns:
            continue
        nav = np.insert((1 + comp_df[col]).cumprod().values, 0, 1.0)
        ax.plot(dates, nav * 100, label=label, color=color, linewidth=lw, linestyle=ls)

    # Shade 2022 bear market (Jan 2022 – Dec 2022)
    ax.axvspan(
        pd.Timestamp("2022-01-01"),
        pd.Timestamp("2022-12-31"),
        alpha=0.12,
        color="#d73027",
        label="2022 bear market",
    )
    ax.axhline(100, color="grey", linewidth=0.5, linestyle="--")

    ax.set_title(
        "Cumulative NAV: Q1 Strategy vs Market Benchmarks (base=100)\n"
        "Net of 0.4% round-trip transaction cost | Dec 2015 – Dec 2025",
        fontsize=12,
        fontweight="bold",
    )
    ax.set_ylabel("NAV (base 100)")
    ax.legend(loc="upper left", fontsize=9)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))
    fig.tight_layout()
    path = CHARTS / "04_benchmark_comparison.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved {path.name}")


def chart_alpha_per_period(comp_df: pd.DataFrame):  # pragma: no cover
    """Q1 excess return vs each benchmark per quarter."""
    fig, axes = plt.subplots(3, 1, figsize=(13, 11), sharex=True)

    bench_cols = [
        ("ew_net", "EW Universe", "#555555"),
        ("SPY_net", "S&P 500", "#d73027"),
        ("ACWI_net", "MSCI ACWI", "#7b3294"),
    ]

    labels = [r["start_date"].strftime("%b'%y") for _, r in comp_df.iterrows()]

    for ax, (col, name, color) in zip(axes, bench_cols):
        if col not in comp_df.columns:
            continue
        alpha = (comp_df["q1_net"] - comp_df[col]) * 100
        bar_colors = ["#2166ac" if v >= 0 else "#d73027" for v in alpha]
        ax.bar(range(len(comp_df)), alpha, color=bar_colors, edgecolor="white", linewidth=0.6)
        ax.axhline(0, color="black", linewidth=0.8)

        avg_alpha = alpha.mean()
        pos = (alpha > 0).sum()
        ax.text(
            0.98,
            0.97,
            f"Avg: {avg_alpha:+.2f}%/qtr\nPositive: {pos}/{len(alpha)}",
            transform=ax.transAxes,
            ha="right",
            va="top",
            fontsize=9,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.9),
        )

        ax.set_ylabel(f"Q1 − {name} (%)")
        ax.set_title(f"Q1 Excess Return vs {name}  (per quarter)")
        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))

        # Shade 2022 bear market
        ax.axvspan(-0.5, 3.5, alpha=0.07, color="#d73027")

    axes[-1].set_xticks(range(len(comp_df)))
    axes[-1].set_xticklabels(labels, rotation=35, ha="right", fontsize=9)

    fig.suptitle(
        "Q1 Quarterly Excess Return vs Benchmarks\n"
        "(Note: Jensen's Alpha requires β-adjustment — see terminal output)\n"
        "Blue = outperformed, Red = underperformed | Shading = 2022 bear market",
        fontsize=11,
        fontweight="bold",
    )
    fig.tight_layout()
    path = CHARTS / "05_benchmark_alpha.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved {path.name}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():  # pragma: no cover
    index_prices = download_index_prices()
    q1_df = load_q1_returns()
    comp_df = build_comparison(q1_df, index_prices)

    comp_df.to_csv(RESULTS / "benchmark_comparison.csv", index=False)

    # ── Print summary ─────────────────────────────────────────────────────────
    strategies = [
        ("q1_net", "Q1 Strategy"),
        ("ew_net", "EW Universe"),
        ("SPY_net", "S&P 500 (SPY)"),
        ("URTH_net", "MSCI World"),
        ("ACWI_net", "MSCI ACWI"),
    ]

    print(f"\n{'='*72}")
    print("PERFORMANCE COMPARISON: Q1 vs MARKET BENCHMARKS (Dec 2015 – Dec 2025)")
    print(f"{'='*72}")
    print(
        f"\n{'Strategy':<22} {'Ann.Return':>12} {'Ann.Vol':>10} {'Sharpe':>8} "
        f"{'Sortino':>8} {'4yr Cum':>10}"
    )
    print("-" * 75)

    for col, label in strategies:
        if col not in comp_df.columns:
            continue
        mask = comp_df[col].notna()
        col_rf = rf_quarterly_series(comp_df.loc[mask, "start_date"])
        s = ann_stats(comp_df.loc[mask, col], rf_q=col_rf)
        print(
            f"  {label:<20} {s['ann_ret']*100:>10.2f}%  "
            f"{s['ann_vol']*100:>8.2f}%  {s['sharpe']:>8.3f}  "
            f"{s['sortino']:>8.3f}  {s['cum']*100:>8.2f}%"
        )

    # Jensen's Alpha vs each benchmark
    rf_label = "3mo T-bill"
    print(f"\n{'='*80}")
    print("Q1 JENSEN'S ALPHA vs BENCHMARKS")
    print(f"Model: (R_Q1 - Rf) = a + b(R_m - Rf) + e   |   Rf = {rf_label}")
    print(f"{'='*80}")
    print(
        f"\n{'Benchmark':<22} {'a (Jensen)':>12} {'b':>7} {'t(a)':>8} "
        f"{'p(a)':>8} {'R^2':>7} {'Excess Ret':>12} {'Beats':>8}"
    )
    print("-" * 88)

    for col, label in strategies[1:]:
        if col not in comp_df.columns:
            continue
        bm_series = comp_df[col].dropna()
        # Align Q1 to benchmark's available periods (keep start_date for rf lookup)
        aligned = comp_df[["start_date", "q1_net", col]].dropna(subset=["q1_net", col])
        aligned_rf = rf_quarterly_series(aligned["start_date"])
        ja = jensen_alpha(aligned["q1_net"], aligned[col], rf_q=aligned_rf)

        # Excess return (kept for reference)
        q1_mask = comp_df["q1_net"].notna()
        q1_rf = rf_quarterly_series(comp_df.loc[q1_mask, "start_date"])
        q1_ann = ann_stats(comp_df.loc[q1_mask, "q1_net"], rf_q=q1_rf)["ann_ret"]
        bm_mask = comp_df[col].notna()
        bm_rf = rf_quarterly_series(comp_df.loc[bm_mask, "start_date"])
        bm_ann = ann_stats(bm_series, rf_q=bm_rf)["ann_ret"]
        excess = q1_ann - bm_ann

        qtr_diff = aligned["q1_net"] - aligned[col]
        hit = (qtr_diff > 0).sum()
        n = len(qtr_diff)

        sig = "*" if ja["p_alpha"] < 0.05 else ("+" if ja["p_alpha"] < 0.10 else "")
        print(
            f"  {label:<20} {ja['alpha']*100:>+10.2f}%{sig}  "
            f"{ja['beta']:>6.3f}  {ja['t_alpha']:>7.2f}  "
            f"{ja['p_alpha']:>7.3f}  {ja['r_squared']:>6.3f}  "
            f"{excess*100:>+10.2f}%  {hit}/{n}"
        )

    print("\n  * p<0.05   + p<0.10")
    print("  Jensen's Alpha: return above what CAPM predicts given beta to each benchmark.")
    print("  Excess Return:  raw annualised return difference (shown for reference).")

    # ── Period detail ─────────────────────────────────────────────────────────
    print(f"\n{'='*72}")
    print("QUARTERLY DETAIL: Q1 vs S&P 500 vs MSCI ACWI")
    print(f"{'='*72}")
    print(f"\n{'Period':<28} {'Q1':>7} {'S&P':>7} {'ACWI':>7} " f"{'vs S&P':>8} {'vs ACWI':>8}")
    print("-" * 68)
    for _, r in comp_df.iterrows():
        q1 = r["q1_net"] * 100
        spy = r.get("SPY_net", np.nan) * 100
        acwi = r.get("ACWI_net", np.nan) * 100
        tag = " [BEAR]" if r["start_date"].year == 2022 else ""
        print(
            f"  {r['start_date'].strftime('%Y-%m-%d')} -> "
            f"{r['end_date'].strftime('%Y-%m-%d')}  "
            f"{q1:>5.2f}%  {spy:>5.2f}%  {acwi:>5.2f}%  "
            f"{q1-spy:>+6.2f}%  {q1-acwi:>+6.2f}%{tag}"
        )

    # ── Charts ────────────────────────────────────────────────────────────────
    print("\nGenerating chart...")
    chart_nav_comparison(comp_df)
    chart_alpha_per_period(comp_df)

    # ── Table PNGs ────────────────────────────────────────────────────────────
    print("Generating table PNGs...")

    # Performance comparison table
    perf_rows = []
    for col, label in strategies:
        if col not in comp_df.columns:
            continue
        mask = comp_df[col].notna()
        s = ann_stats(
            comp_df.loc[mask, col], rf_q=rf_quarterly_series(comp_df.loc[mask, "start_date"])
        )
        perf_rows.append(
            [
                label,
                f"{s['ann_ret']*100:.2f}%",
                f"{s['ann_vol']*100:.2f}%",
                f"{s['sharpe']:.3f}",
                f"{s['sortino']:.3f}",
                f"{s['cum']*100:.1f}%",
            ]
        )
    save_table_png(
        headers=["Strategy", "Ann. Return", "Ann. Vol", "Sharpe", "Sortino", "Cumulative"],
        rows=perf_rows,
        title="Performance Comparison: Q1 vs Market Benchmarks\n"
        "40 quarters, Dec 2015–Dec 2025  |  Net of 0.4% TC  |  Rf = 3mo T-bill",
        filepath=CHARTS / "04b_performance_table.png",
        col_widths=[2.5, 1.5, 1.4, 1.2, 1.2, 1.4],
        highlight_rows=[0],  # Q1 Strategy
        bold_rows=[0],
        figsize=(11, 5),
    )

    # Jensen's Alpha table
    ja_rows = []
    for col, label in strategies[1:]:
        if col not in comp_df.columns:
            continue
        aligned = comp_df[["start_date", "q1_net", col]].dropna(subset=["q1_net", col])
        aligned_rf = rf_quarterly_series(aligned["start_date"])
        ja = jensen_alpha(aligned["q1_net"], aligned[col], rf_q=aligned_rf)
        q1_mask = comp_df["q1_net"].notna()
        q1_ann = ann_stats(
            comp_df.loc[q1_mask, "q1_net"],
            rf_q=rf_quarterly_series(comp_df.loc[q1_mask, "start_date"]),
        )["ann_ret"]
        bm_mask = comp_df[col].notna()
        bm_ann = ann_stats(
            comp_df.loc[bm_mask, col],
            rf_q=rf_quarterly_series(comp_df.loc[bm_mask, "start_date"]),
        )["ann_ret"]
        excess = q1_ann - bm_ann
        beat = (aligned["q1_net"] - aligned[col]).gt(0).sum()
        sig = "*" if ja["p_alpha"] < 0.05 else ("†" if ja["p_alpha"] < 0.10 else "")
        ja_rows.append(
            [
                label,
                f"{ja['alpha']*100:+.2f}%{sig}",
                f"{ja['beta']:.3f}",
                f"{ja['t_alpha']:.2f}",
                f"{ja['p_alpha']:.3f}",
                f"{ja['r_squared']:.3f}",
                f"{excess*100:+.2f}%",
                f"{beat}/{len(aligned)}",
            ]
        )
    save_table_png(
        headers=["Benchmark", "Jensen's α", "β", "t(α)", "p(α)", "R²", "Excess Ret", "Beats"],
        rows=ja_rows,
        title="Jensen's Alpha: Q1 vs Benchmarks\n"
        "Model: (R_Q1 − Rf) = α + β(R_m − Rf) + ε  |  * p<0.05  † p<0.10",
        filepath=CHARTS / "04c_jensens_alpha_table.png",
        col_widths=[2.2, 1.4, 0.9, 0.9, 0.9, 0.9, 1.4, 1.0],
        footnote="Jensen's Alpha = return above CAPM prediction given β to benchmark. "
        "Excess Return (raw difference) shown for reference.",
        figsize=(13, 4),
    )

    print(f"\nSaved to {RESULTS}")


if __name__ == "__main__":
    main()
