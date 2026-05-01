"""Step 09 — Long-Short Portfolio Backtest (optional robustness test).

Constructs a dollar-neutral long-short portfolio:
  LONG  Q1 (top 20% composite score) — equal weighted
  SHORT Q5 (bottom 20% composite score) — equal weighted

Transaction costs:
  Long leg:  0.4% round-trip (same as long-only)
  Short leg: 0.4% round-trip + 0.5% annualised stock borrow cost
             = 0.4% + 0.125% per quarter = 0.525% per quarter

Long-short return = Long Q1 net return - Short Q5 net return
  (if Q1 > Q5: positive — factor worked)
  (if Q1 < Q5: negative — factor did not work)

Outputs:
  results/long_short_returns.csv
  results/charts/10_long_short_cumulative.png
  results/charts/11_long_short_per_period.png
  results/charts/12_long_short_q1q5.png

Usage:
    cd team_russell/coursework_one
    poetry run python ../coursework_two/scripts/step09_long_short.py
"""

import sys
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns

sys.path.insert(0, str(Path(__file__).parent))
from _table_utils import save_table_png

warnings.filterwarnings("ignore")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE = Path(__file__).parent.parent
RESULTS = BASE / "results"
CHARTS = BASE / "results" / "charts"
CHARTS.mkdir(parents=True, exist_ok=True)

STOCK_CSV = RESULTS / "stock_returns_10year.csv"

# ── Config ────────────────────────────────────────────────────────────────────
TC_RT = 0.004  # 0.4% round-trip transaction cost
BORROW_COST_PER_QUARTER = 0.005  # 2% p.a. stock borrow cost on short leg
from _rf_rates import rf_quarterly_series  # noqa: E402

# ── Style ─────────────────────────────────────────────────────────────────────
sns.set_theme(style="whitegrid", palette="muted", font_scale=1.05)


# ── Load and aggregate data ───────────────────────────────────────────────────
def load_data() -> pd.DataFrame:  # pragma: no cover
    """Aggregate stock_returns_10year.csv to quintile-level returns per period."""
    df = pd.read_csv(STOCK_CSV)
    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(df["end_date"])
    df["quintile"] = pd.to_numeric(df["quintile"], errors="coerce")
    df = df.dropna(subset=["quintile", "gross_return"])
    df["quintile"] = df["quintile"].astype(int)

    rows = []
    for (s, e), grp in df.groupby(["start_date", "end_date"]):
        q1 = grp[grp["quintile"] == 1]
        q5 = grp[grp["quintile"] == 5]
        if q1.empty or q5.empty:
            continue
        rows.append(
            {
                "start_date": s,
                "end_date": e,
                "q1_gross": q1["gross_return"].mean(),
                "q5_gross": q5["gross_return"].mean(),
                "bm_gross": grp["gross_return"].mean(),  # EW universe
            }
        )
    return pd.DataFrame(rows).sort_values("start_date").reset_index(drop=True)


# ── Build long-short returns ──────────────────────────────────────────────────
def build_ls(raw: pd.DataFrame) -> pd.DataFrame:
    ls_rows = []
    for _, r in raw.iterrows():
        # Long Q1: pay round-trip cost
        q1_net = r["q1_gross"] - TC_RT

        # Short Q5: profit = -(Q5 return); pay borrow + round-trip cost
        q5_short_net = -r["q5_gross"] - BORROW_COST_PER_QUARTER - TC_RT

        # Dollar-neutral L/S: average of long and short leg
        ls_return = (q1_net + q5_short_net) / 2

        ls_rows.append(
            {
                "start_date": r["start_date"],
                "end_date": r["end_date"],
                "q1_gross": r["q1_gross"],
                "q5_gross": r["q5_gross"],
                "q1_net": q1_net,
                "q5_short_net": q5_short_net,
                "ls_return": ls_return,
                "bm_net": r["bm_gross"] - TC_RT,
            }
        )
    return pd.DataFrame(ls_rows)


# ── Summary stats ─────────────────────────────────────────────────────────────
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
    nav = (1 + series).cumprod()
    peak = nav.cummax()
    max_dd = ((peak - nav) / peak).max()
    return {
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "hit_rate": (series > 0).mean(),
        "max_dd": max_dd,
    }


# ── Charts ────────────────────────────────────────────────────────────────────
def chart_ls_cumulative(ls_df: pd.DataFrame):  # pragma: no cover
    dates = [ls_df["start_date"].iloc[0]] + list(ls_df["end_date"])
    nav_ls = np.insert((1 + ls_df["ls_return"]).cumprod().values, 0, 1.0)
    nav_lo = np.insert((1 + ls_df["q1_net"]).cumprod().values, 0, 1.0)
    nav_bm = np.insert((1 + ls_df["bm_net"]).cumprod().values, 0, 1.0)

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(
        dates, nav_ls * 100, label="Long-Short (Q1 long, Q5 short)", color="#6a3d9a", linewidth=2.5
    )
    ax.plot(
        dates, nav_lo * 100, label="Long-Only Q1", color="#2166ac", linewidth=2.0, linestyle="--"
    )
    ax.plot(dates, nav_bm * 100, label="EW Universe", color="black", linewidth=1.5, linestyle=":")
    ax.axhline(100, color="grey", linewidth=0.5, linestyle="--")
    ax.set_title(
        "Cumulative NAV: Long-Short vs Long-Only vs EW Universe (base=100)\n"
        "Net of transaction costs + 0.5% p.a. stock borrow cost on short leg",
        fontsize=12,
        fontweight="bold",
    )
    ax.set_ylabel("NAV (base 100)")
    ax.legend(loc="upper left")
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))
    fig.tight_layout()
    path = CHARTS / "10_long_short_cumulative.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved {path.name}")


def chart_ls_per_period(ls_df: pd.DataFrame):  # pragma: no cover
    labels = [r["start_date"].strftime("%b'%y") for _, r in ls_df.iterrows()]
    colors = ["#6a3d9a" if v > 0 else "#d73027" for v in ls_df["ls_return"]]
    s = ann_stats(ls_df["ls_return"], rf_quarterly_series(ls_df["start_date"]))

    fig, ax = plt.subplots(figsize=(13, 5))
    ax.bar(
        range(len(ls_df)), ls_df["ls_return"] * 100, color=colors, edgecolor="white", linewidth=0.8
    )
    ax.set_xticks(range(len(ls_df)))
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
    ax.axhline(0, color="black", linewidth=0.8)

    wins = (ls_df["ls_return"] > 0).sum()
    ax.text(
        0.98,
        0.97,
        f"Works: {wins}/{len(ls_df)} quarters\n"
        f"Ann. Return: {s['ann_ret']*100:.2f}%\n"
        f"Sharpe: {s['sharpe']:.3f}\n"
        f"Sortino: {s['sortino']:.3f}",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=9,
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white", alpha=0.9),
    )
    ax.set_title(
        "Long-Short Return per Quarter\n" "Purple = factor worked (Q1 > Q5), Red = factor failed",
        fontsize=12,
        fontweight="bold",
    )
    ax.set_ylabel("Long-Short Net Return (%)")
    fig.tight_layout()
    path = CHARTS / "11_long_short_per_period.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved {path.name}")


def chart_q1_q5_grouped(ls_df: pd.DataFrame):  # pragma: no cover
    x = np.arange(len(ls_df))
    width = 0.35
    labels = [r["start_date"].strftime("%b'%y") for _, r in ls_df.iterrows()]

    fig, ax = plt.subplots(figsize=(13, 5))
    ax.bar(
        x - width / 2,
        ls_df["q1_gross"] * 100,
        width,
        label="Q1 (Long)",
        color="#2166ac",
        edgecolor="white",
    )
    ax.bar(
        x + width / 2,
        ls_df["q5_gross"] * 100,
        width,
        label="Q5 (Short target)",
        color="#d73027",
        edgecolor="white",
    )
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_title(
        "Q1 vs Q5 Gross Returns per Quarter\n" "Long-Short works when Q1 bar > Q5 bar",
        fontsize=12,
        fontweight="bold",
    )
    ax.set_ylabel("Gross Return (%)")
    ax.legend()
    fig.tight_layout()
    path = CHARTS / "12_long_short_q1q5.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved {path.name}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():  # pragma: no cover
    print("Step 09 — Long-Short Backtest (optional)")
    raw = load_data()
    ls_df = build_ls(raw)

    # ── Summary stats ─────────────────────────────────────────────────────────
    rf_q_series = rf_quarterly_series(ls_df["start_date"])
    s_ls = ann_stats(ls_df["ls_return"], rf_q=rf_q_series)
    s_lo = ann_stats(ls_df["q1_net"], rf_q=rf_q_series)

    print(f"\n{'='*65}")
    print("LONG-SHORT vs LONG-ONLY COMPARISON")
    print(f"{'='*65}")
    print(
        f"\n{'Strategy':<25} {'Ann.Return':>12} {'Ann.Vol':>10} {'Sharpe':>8} "
        f"{'Sortino':>8} {'HitRate':>9} {'MaxDD':>8}"
    )
    print("-" * 85)
    for label, s in [("Long-Short (Q1-Q5)", s_ls), ("Long-Only Q1", s_lo)]:
        print(
            f"  {label:<23} {s['ann_ret']*100:>10.2f}%  {s['ann_vol']*100:>8.2f}%  "
            f"{s['sharpe']:>8.3f}  {s['sortino']:>8.3f}  {s['hit_rate']*100:>7.1f}%  "
            f"{s['max_dd']*100:>6.2f}%"
        )

    print("\nLong-Short period detail:")
    print(f"{'Period':<28} {'Q1':>7} {'Q5':>7} {'L-S':>8} {'Result':>8}")
    print("-" * 57)
    for _, row in ls_df.iterrows():
        result = "OK" if row["ls_return"] > 0 else "FAIL"
        print(
            f"  {row['start_date'].strftime('%Y-%m-%d')} -> "
            f"{row['end_date'].strftime('%Y-%m-%d')}  "
            f"{row['q1_gross']*100:>5.2f}%  {row['q5_gross']*100:>5.2f}%  "
            f"{row['ls_return']*100:>6.2f}%  {result}"
        )

    print("\nLong-Short summary:")
    print(f"  Works in: {(ls_df['ls_return'] > 0).sum()}/{len(ls_df)} quarters")
    print(f"  Best quarter:  {ls_df['ls_return'].max()*100:.2f}%")
    print(f"  Worst quarter: {ls_df['ls_return'].min()*100:.2f}%")
    print(f"  Max drawdown:  {s_ls['max_dd']*100:.2f}%")

    ls_df.to_csv(RESULTS / "long_short_returns.csv", index=False)
    print("\nGenerating charts...")
    chart_ls_cumulative(ls_df)
    chart_ls_per_period(ls_df)
    chart_q1_q5_grouped(ls_df)

    # ── Table PNGs ────────────────────────────────────────────────────────────
    print("Generating table PNGs...")

    # Summary comparison table
    summary_rows = []
    for label, s in [("Long-Short (Q1 long, Q5 short)", s_ls), ("Long-Only Q1", s_lo)]:
        summary_rows.append(
            [
                label,
                f"{s['ann_ret']*100:.2f}%",
                f"{s['ann_vol']*100:.2f}%",
                f"{s['sharpe']:.3f}",
                f"{s['sortino']:.3f}",
                f"{s['hit_rate']*100:.1f}%",
                f"{s['max_dd']*100:.2f}%",
            ]
        )
    save_table_png(
        headers=[
            "Strategy",
            "Ann. Return",
            "Ann. Vol",
            "Sharpe",
            "Sortino",
            "Hit Rate",
            "Max Drawdown",
        ],
        rows=summary_rows,
        title="Long-Short vs Long-Only Q1 — Performance Summary\n"
        f"40 quarters, Dec 2015–Dec 2025  |  L/S works in "
        f"{(ls_df['ls_return'] > 0).sum()}/{len(ls_df)} quarters  |  "
        f"Net of TC + 0.5% p.a. borrow on short",
        filepath=CHARTS / "10b_long_short_summary_table.png",
        col_widths=[3.2, 1.4, 1.3, 1.1, 1.1, 1.2, 1.5],
        highlight_rows=[1],  # Long-Only Q1
        bold_rows=[1],
        figsize=(12, 3.5),
    )

    # Per-period detail table
    detail_rows = []
    for _, row in ls_df.iterrows():
        result = "OK" if row["ls_return"] > 0 else "FAIL"
        detail_rows.append(
            [
                f"{row['start_date'].strftime('%Y-%m-%d')} → {row['end_date'].strftime('%Y-%m-%d')}",
                f"{row['q1_gross']*100:.2f}%",
                f"{row['q5_gross']*100:.2f}%",
                f"{row['ls_return']*100:.2f}%",
                result,
            ]
        )
    ok_idx = [i for i, r in enumerate(detail_rows) if r[4] == "OK"]
    save_table_png(
        headers=["Period", "Q1 Gross", "Q5 Gross", "L-S Net", "Result"],
        rows=detail_rows,
        title="Long-Short Return per Quarter\n"
        "Long Q1 (gross) − Short Q5 (gross) − TC − Borrow Cost",
        filepath=CHARTS / "10c_long_short_detail_table.png",
        col_widths=[3.5, 1.2, 1.2, 1.2, 0.9],
        highlight_rows=ok_idx,
        figsize=(10, 14),
        fontsize=8,
    )

    print(f"\nAll long-short results saved to {RESULTS}")


if __name__ == "__main__":
    main()
