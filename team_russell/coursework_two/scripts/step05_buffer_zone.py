"""Step 05 — Buffer Zone Turnover Constraint (Robustness Test).

Reads directly from the 40-quarter dataset (stock_returns_10year.csv).
No PostgreSQL dependency.

Buffer zone rule (industry standard — used by MSCI, FTSE Russell, AQR):
  - Entry threshold: stock must score in the top 15% to enter Q1
  - Exit threshold:  stock only exits Q1 if it falls below the top 25%
  - Stocks in the 15–25% zone: existing members STAY, new stocks don't enter

This reduces unnecessary churn from stocks drifting marginally across
the 20% quintile boundary, without changing the strategy signal.

Outputs:
  results/buffer_comparison.csv
  results/charts/05_buffer_zone.png

Usage:
    cd team_russell/coursework_one
    poetry run python ../coursework_two/scripts/step05_buffer_zone.py
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
sns.set_theme(style="whitegrid", palette="muted", font_scale=1.05)

BASE = Path(__file__).parent.parent
RESULTS = BASE / "results"
CHARTS = RESULTS / "charts"
CHARTS.mkdir(parents=True, exist_ok=True)

ENTRY_PCT = 0.15  # must be in top 15% to enter buffered Q1
EXIT_PCT = 0.25  # must fall below top 25% to exit buffered Q1
TC_RT = 0.004

# Mean annualised 3-month T-bill yield (^IRX) over Dec 2015 – Dec 2025
from _rf_rates import rf_quarterly_series  # noqa: E402


# ── Load data ─────────────────────────────────────────────────────────────────
def load_returns() -> pd.DataFrame:  # pragma: no cover
    """Load the full 40-quarter stock-level dataset."""
    df = pd.read_csv(RESULTS / "stock_returns_10year.csv")
    df["start_date"] = pd.to_datetime(df["start_date"])
    df["end_date"] = pd.to_datetime(df["end_date"])
    df["quintile"] = pd.to_numeric(df["quintile"], errors="coerce")
    return df.dropna(subset=["quintile", "composite_score"])


# ── Build buffered Q1 memberships ─────────────────────────────────────────────
def build_buffered_memberships(df: pd.DataFrame) -> dict:
    """
    Returns {start_date: set(symbols)} for the buffered Q1.

    First period: hard top-20% (no prior membership to buffer from).
    Subsequent periods: apply entry/exit buffer thresholds.
    """
    dates = sorted(df["start_date"].unique())
    memberships = {}

    for i, d in enumerate(dates):
        sub = (
            df[df["start_date"] == d]
            .sort_values("composite_score", ascending=False)
            .reset_index(drop=True)
        )
        n = len(sub)
        sub["rank_pct"] = sub.index / n  # 0 = best, 1 = worst

        if i == 0:
            buffered = set(sub[sub["rank_pct"] < 0.20]["symbol"])
        else:
            prev = memberships[dates[i - 1]]
            entry = set(sub[sub["rank_pct"] < ENTRY_PCT]["symbol"])
            stay = set(sub[sub["rank_pct"] < EXIT_PCT]["symbol"])
            buffered = (prev & stay) | (entry - prev)

            # Cap at 130% of target size to avoid unbounded growth
            target = round(n * 0.20)
            if len(buffered) > target * 1.3:
                ranked = sub[sub["symbol"].isin(buffered)]
                buffered = set(ranked.head(target)["symbol"])

        memberships[d] = buffered

    return memberships


# ── Portfolio returns ─────────────────────────────────────────────────────────
def compute_returns(
    memberships: dict, df: pd.DataFrame, use_original_q1: bool = False
) -> pd.DataFrame:
    """Equal-weighted net return per period for a given membership dict."""
    periods = sorted(df[["start_date", "end_date"]].drop_duplicates().itertuples(index=False))
    rows = []
    for p in periods:
        s, e = p.start_date, p.end_date
        period_df = df[(df["start_date"] == s) & (df["end_date"] == e)]
        if period_df.empty:  # pragma: no cover
            continue

        if use_original_q1:
            portfolio = period_df[period_df["quintile"] == 1]
        else:
            members = memberships.get(s, set())
            portfolio = period_df[period_df["symbol"].isin(members)]

        if len(portfolio) < 5:
            continue

        gross = portfolio["gross_return"].mean()
        rows.append(
            {
                "start_date": s,
                "end_date": e,
                "n_stocks": len(portfolio),
                "gross_return": gross,
                "net_return": gross - TC_RT,
                "bm_net": period_df["gross_return"].mean() - TC_RT,
            }
        )
    return pd.DataFrame(rows)


# ── Turnover ──────────────────────────────────────────────────────────────────
def compute_turnover(memberships: dict) -> pd.DataFrame:
    dates = sorted(memberships.keys())
    rows = []
    for i in range(len(dates) - 1):
        d_from = dates[i]
        d_to = dates[i + 1]
        s_from = memberships[d_from]
        s_to = memberships[d_to]
        avg = (len(s_from) + len(s_to)) / 2
        rate = (len(s_from - s_to) + len(s_to - s_from)) / (2 * avg) * 100 if avg > 0 else 0
        rows.append({"from_date": d_from, "to_date": d_to, "turnover_rate": round(rate, 1)})
    return pd.DataFrame(rows)


# ── Summary stats ─────────────────────────────────────────────────────────────
def summary(ret_df: pd.DataFrame) -> dict:
    r = ret_df["net_return"]
    ann = (1 + r.mean()) ** 4 - 1
    vol = r.std(ddof=1) * np.sqrt(4)
    rf_q = rf_quarterly_series(ret_df["start_date"])
    excess = r.values - rf_q.values
    ann_excess = float(np.mean(excess)) * 4
    return {
        "ann_return": ann,
        "ann_vol": vol,
        "sharpe": ann_excess / vol if vol > 0 else np.nan,
        "cum": (1 + r).prod() - 1,
    }


# ── Chart ─────────────────────────────────────────────────────────────────────
def chart(
    orig_to: pd.DataFrame,
    buf_to: pd.DataFrame,  # pragma: no cover
    orig_ret: pd.DataFrame,
    buf_ret: pd.DataFrame,
):
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Left: turnover comparison
    ax = axes[0]
    x = np.arange(len(orig_to))
    w = 0.38
    ax.bar(
        x - w / 2,
        orig_to["turnover_rate"],
        w,
        label=f"Original (avg {orig_to['turnover_rate'].mean():.1f}%)",
        color="#d73027",
        alpha=0.85,
        edgecolor="white",
    )
    ax.bar(
        x + w / 2,
        buf_to["turnover_rate"],
        w,
        label=f"Buffered (avg {buf_to['turnover_rate'].mean():.1f}%)",
        color="#2166ac",
        alpha=0.85,
        edgecolor="white",
    )
    ax.axhline(
        orig_to["turnover_rate"].mean(), color="#d73027", linewidth=1, linestyle="--", alpha=0.6
    )
    ax.axhline(
        buf_to["turnover_rate"].mean(), color="#2166ac", linewidth=1, linestyle="--", alpha=0.6
    )
    labels = [r.from_date.strftime("%b'%y") for r in orig_to.itertuples()]
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("Turnover Rate (%)")
    ax.set_title(
        "Q1 Turnover: Original vs Buffered\n(15% entry / 25% exit)", fontsize=11, fontweight="bold"
    )
    ax.legend(fontsize=9)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))

    # Right: cumulative NAV comparison
    ax2 = axes[1]
    nav_o = np.insert((1 + orig_ret["net_return"]).cumprod().values, 0, 1.0) * 100
    nav_b = np.insert((1 + buf_ret["net_return"]).cumprod().values, 0, 1.0) * 100
    nav_m = np.insert((1 + orig_ret["bm_net"]).cumprod().values, 0, 1.0) * 100
    dates = [orig_ret["start_date"].iloc[0]] + list(orig_ret["end_date"])
    ax2.plot(dates, nav_o, label="Original Q1", color="#d73027", lw=2, linestyle="--")
    ax2.plot(dates, nav_b, label="Buffered Q1", color="#2166ac", lw=2.5)
    ax2.plot(dates, nav_m, label="EW Universe", color="black", lw=1.5, linestyle=":")
    ax2.axhline(100, color="grey", linewidth=0.5, linestyle="--")
    ax2.set_title(
        "Cumulative NAV: Original vs Buffered Q1\n(base=100, net of 0.4% TC)",
        fontsize=11,
        fontweight="bold",
    )
    ax2.set_ylabel("NAV (base 100)")
    ax2.legend(fontsize=9)
    ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))

    fig.tight_layout()
    out = CHARTS / "05_buffer_zone.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {out.name}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():  # pragma: no cover
    print("Loading 40-quarter dataset...")
    df = load_returns()
    n_periods = df["start_date"].nunique()
    print(f"  {len(df):,} rows across {n_periods} rebalance dates")

    # Build memberships
    print("Building buffered Q1 memberships...")
    buf_mem = build_buffered_memberships(df)

    # Original Q1 memberships from quintile column
    orig_mem = {
        d: set(df[(df["start_date"] == d) & (df["quintile"] == 1)]["symbol"])
        for d in sorted(df["start_date"].unique())
    }

    # Turnover
    orig_to = compute_turnover(orig_mem)
    buf_to = compute_turnover(buf_mem)

    # Returns
    orig_ret = compute_returns(orig_mem, df, use_original_q1=True)
    buf_ret = compute_returns(buf_mem, df, use_original_q1=False)

    s_orig = summary(orig_ret)
    s_buf = summary(buf_ret)

    # Print results
    print(f"\n{'='*65}")
    print(f"BUFFER ZONE RESULTS  ({n_periods} quarters, Dec 2015 – Dec 2025)")
    print(f"{'='*65}")
    print(f"\n{'Metric':<30} {'Original':>12} {'Buffered':>12} {'Change':>10}")
    print("-" * 65)
    avg_o = orig_to["turnover_rate"].mean()
    avg_b = buf_to["turnover_rate"].mean()
    ann_o = (1 - (1 - avg_o / 100) ** 4) * 100
    ann_b = (1 - (1 - avg_b / 100) ** 4) * 100
    rows = [
        ("Avg quarterly turnover", f"{avg_o:.1f}%", f"{avg_b:.1f}%", f"{avg_b-avg_o:+.1f}pp"),
        ("Implied annual turnover", f"~{ann_o:.0f}%", f"~{ann_b:.0f}%", f"{ann_b-ann_o:+.0f}pp"),
        (
            "Ann. net return",
            f"{s_orig['ann_return']*100:.2f}%",
            f"{s_buf['ann_return']*100:.2f}%",
            f"{(s_buf['ann_return']-s_orig['ann_return'])*100:+.2f}pp",
        ),
        (
            "Ann. volatility",
            f"{s_orig['ann_vol']*100:.2f}%",
            f"{s_buf['ann_vol']*100:.2f}%",
            f"{(s_buf['ann_vol']-s_orig['ann_vol'])*100:+.2f}pp",
        ),
        (
            "Sharpe ratio",
            f"{s_orig['sharpe']:.3f}",
            f"{s_buf['sharpe']:.3f}",
            f"{s_buf['sharpe']-s_orig['sharpe']:+.3f}",
        ),
    ]
    for label, vo, vb, ch in rows:
        print(f"  {label:<28} {vo:>12} {vb:>12} {ch:>10}")

    # Save CSV
    comp = []
    for (_, oi), (_, bi) in zip(orig_to.iterrows(), buf_to.iterrows()):
        d = oi["from_date"]
        or_ = orig_ret[orig_ret["start_date"] == d]
        br_ = buf_ret[buf_ret["start_date"] == d]
        comp.append(
            {
                "from_date": d,
                "to_date": oi["to_date"],
                "orig_turnover": oi["turnover_rate"],
                "buf_turnover": bi["turnover_rate"],
                "orig_net_return": or_["net_return"].values[0] if len(or_) else np.nan,
                "buf_net_return": br_["net_return"].values[0] if len(br_) else np.nan,
            }
        )
    pd.DataFrame(comp).to_csv(RESULTS / "buffer_comparison.csv", index=False)
    print("\n  Saved buffer_comparison.csv")

    print("\nGenerating chart...")
    chart(orig_to, buf_to, orig_ret, buf_ret)

    # ── Table PNG ─────────────────────────────────────────────────────────────
    avg_o = orig_to["turnover_rate"].mean()
    avg_b = buf_to["turnover_rate"].mean()
    ann_o = (1 - (1 - avg_o / 100) ** 4) * 100
    ann_b = (1 - (1 - avg_b / 100) ** 4) * 100
    table_rows = [
        ("Avg quarterly turnover", f"{avg_o:.1f}%", f"{avg_b:.1f}%", f"{avg_b-avg_o:+.1f}pp"),
        ("Implied annual turnover", f"~{ann_o:.0f}%", f"~{ann_b:.0f}%", f"{ann_b-ann_o:+.0f}pp"),
        (
            "Ann. net return",
            f"{s_orig['ann_return']*100:.2f}%",
            f"{s_buf['ann_return']*100:.2f}%",
            f"{(s_buf['ann_return']-s_orig['ann_return'])*100:+.2f}pp",
        ),
        (
            "Ann. volatility",
            f"{s_orig['ann_vol']*100:.2f}%",
            f"{s_buf['ann_vol']*100:.2f}%",
            f"{(s_buf['ann_vol']-s_orig['ann_vol'])*100:+.2f}pp",
        ),
        (
            "Sharpe ratio",
            f"{s_orig['sharpe']:.3f}",
            f"{s_buf['sharpe']:.3f}",
            f"{s_buf['sharpe']-s_orig['sharpe']:+.3f}",
        ),
    ]
    save_table_png(
        headers=["Metric", "Original Q1", "Buffered Q1 (15/25)", "Change"],
        rows=[list(r) for r in table_rows],
        title="Buffer Zone Comparison: Original vs Buffered Q1\n"
        "Entry threshold: top 15%  |  Exit threshold: top 25%  |  40 quarters",
        filepath=CHARTS / "05b_buffer_comparison_table.png",
        col_widths=[2.5, 1.5, 2.0, 1.3],
        highlight_rows=[2, 4],  # ann return and Sharpe
        figsize=(10, 4),
    )


if __name__ == "__main__":
    main()
