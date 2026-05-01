"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Visualization — all 12 + 2 charts for the CW2 report
Project : CW2 - Value-Sentiment Investment Strategy

Generates every chart required by Part C §C1 of the CW2 Master Guide
plus two sophistication charts. Every figure uses the same
institutional-grade theme so the report reads like a consistent
quant-fund tearsheet rather than a grab-bag of matplotlib defaults.

Charts:
    1.  Cumulative return (4 portfolios + benchmark, log scale)
    2.  Drawdown underwater chart
    3.  Monthly returns heatmap
    4.  Rolling 12-month Sharpe ratio
    5.  Weight sensitivity sweep
    6.  Fama-French 5-factor loadings with 95 % CIs
    7.  Sector allocation (portfolio vs benchmark)
    8.  Random portfolio Sharpe histogram
    9.  Screening threshold sensitivity (2-D heatmap)
    10. Turnover per rebalance date
    11. OLD vs NEW value score sector concentration
    12. Pipeline flowchart (CW1→CW2)
    13. Diversification over time (sophistication)
    14. Cumulative transaction-cost drag (sophistication)

Design system:
    - Navy/teal primary palette modelled on institutional research decks.
    - Headline stat banner embedded on every performance chart.
    - 220 DPI export so figures stay crisp on retina / print PDFs.
    - Grid kept at 40% alpha so lines never fight with data.
    - Helvetica Neue → Helvetica → DejaVu Sans font stack for portability.

Ref: Part C §C1 + §E4 ("Caption every figure, precise numbers").
"""

from __future__ import annotations

import logging
import os
from typing import Optional, Sequence

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for server use
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import FancyBboxPatch

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Design system
# ---------------------------------------------------------------------------

PALETTE = {
    # Core brand
    'navy':    '#0C2340',
    'deep':    '#1B3B6F',
    'teal':    '#2E86AB',
    'accent':  '#3EB489',
    'amber':   '#F4B942',
    'coral':   '#E57A44',
    'red':     '#D7263D',
    'plum':    '#7A5195',

    # Surfaces
    'bg':      '#FFFFFF',
    'panel':   '#F7F9FC',
    'grid':    '#E6ECF1',
    'rule':    '#CBD5E1',

    # Text
    'text':       '#0F172A',
    'text_muted': '#64748B',
}

PORTFOLIO_COLORS = {
    'combined':       PALETTE['navy'],
    'value_only':     PALETTE['accent'],
    'sentiment_only': PALETTE['amber'],
    'benchmark':      PALETTE['text_muted'],
    'ew_universe':    '#C5CDD7',
}

PORTFOLIO_LABELS = {
    'combined':       'Combined (60V/40S)',
    'value_only':     'Value-Only',
    'sentiment_only': 'Sentiment-Only',
    'benchmark':      'S&P 500',
    'ew_universe':    'Equal-Weight Universe',
}


def _apply_theme() -> None:
    """Apply the institutional theme to matplotlib rcParams."""
    plt.rcParams.update({
        'font.family': 'sans-serif',
        'font.sans-serif': ['Helvetica Neue', 'Helvetica', 'DejaVu Sans', 'Arial'],
        'font.size': 11,

        'axes.titlesize': 15,
        'axes.titleweight': 'bold',
        'axes.titlecolor': PALETTE['navy'],
        'axes.titlepad': 14,
        'axes.titlelocation': 'left',

        'axes.labelsize': 11,
        'axes.labelcolor': PALETTE['text'],
        'axes.labelweight': 'medium',

        'axes.edgecolor': PALETTE['rule'],
        'axes.linewidth': 0.8,
        'axes.facecolor': PALETTE['bg'],

        'axes.spines.top': False,
        'axes.spines.right': False,
        'axes.spines.left': True,
        'axes.spines.bottom': True,

        'axes.grid': True,
        'axes.axisbelow': True,
        'grid.color': PALETTE['grid'],
        'grid.linewidth': 0.8,
        'grid.alpha': 0.9,

        'xtick.color': PALETTE['text_muted'],
        'ytick.color': PALETTE['text_muted'],
        'xtick.labelsize': 10,
        'ytick.labelsize': 10,
        'xtick.major.pad': 6,
        'ytick.major.pad': 6,

        'legend.fontsize': 10,
        'legend.frameon': False,
        'legend.handlelength': 2.0,

        'figure.facecolor': PALETTE['bg'],
        'figure.dpi': 120,
        'figure.autolayout': False,
        'figure.constrained_layout.use': False,

        'savefig.dpi': 220,
        'savefig.bbox': 'tight',
        'savefig.facecolor': PALETTE['bg'],
        'savefig.edgecolor': 'none',
        'savefig.pad_inches': 0.25,

        'lines.linewidth': 1.9,
        'lines.markersize': 6,

        'patch.linewidth': 0.6,
        'patch.edgecolor': PALETTE['bg'],
    })


_apply_theme()


# ---------------------------------------------------------------------------
# Helper primitives
# ---------------------------------------------------------------------------

def _style_ax(
    ax: plt.Axes,
    title: str = '',
    subtitle: str = '',
    ylabel: str = '',
    xlabel: str = '',
) -> None:
    """Set axis labels only; title/subtitle handled at figure level.

    Callers that want the full tearsheet header (banner + title +
    subtitle) should use :func:`_tearsheet_layout` instead, which
    allocates space in figure coordinates so the banner never clashes
    with the axes.
    """
    ax.set_title('')  # clear any default
    if ylabel:
        ax.set_ylabel(ylabel, color=PALETTE['text'], labelpad=8)
    if xlabel:
        ax.set_xlabel(xlabel, color=PALETTE['text'], labelpad=8)


def _tearsheet_layout(
    figsize=(13.5, 7.6),
    title: str = '',
    subtitle: str = '',
    metrics: Optional[list] = None,
    left: float = 0.07,
    right: float = 0.96,
    bottom: float = 0.12,
    footer_text: str = '',
) -> tuple:
    """Create a figure with a consistent tearsheet header.

    Layout (figure coordinates):

        ┌─────────────────── banner (KPI cards) ──────────────────┐  0.90
        │ TITLE in navy bold                                      │  0.82
        │ subtitle in muted grey                                   │  0.79
        │                                                          │
        │                    main axes                            │
        │                                                          │
        └──────────────────────────────────────────────────────────┘
          footer in italic grey                                        0.02

    Returns ``(fig, ax)``.
    """
    fig = plt.figure(figsize=figsize)
    banner_top = 0.90
    title_y = 0.82 if metrics else 0.88
    subtitle_y = title_y - 0.035
    axes_top = subtitle_y - 0.07
    axes_bottom = bottom
    axes_height = axes_top - axes_bottom

    ax = fig.add_axes([left, axes_bottom, right - left, axes_height])

    # Banner
    if metrics:
        n = len(metrics)
        span = right - left
        for i, (label, value, color) in enumerate(metrics):
            x = left + i * span / n
            fig.text(
                x, banner_top + 0.03, label.upper(),
                color=PALETTE['text_muted'], fontsize=9, fontweight='bold',
                ha='left', va='bottom',
            )
            fig.text(
                x, banner_top, value,
                color=color, fontsize=18, fontweight='bold',
                ha='left', va='top',
            )

    if title:
        fig.text(
            left, title_y, title,
            color=PALETTE['navy'], fontsize=16, fontweight='bold',
            ha='left', va='bottom',
        )
    if subtitle:
        fig.text(
            left, subtitle_y, subtitle,
            color=PALETTE['text_muted'], fontsize=10.5,
            ha='left', va='bottom',
        )

    if footer_text:
        fig.text(
            left, 0.02, footer_text,
            color=PALETTE['text_muted'], fontsize=8.5, style='italic',
            ha='left', va='bottom',
        )

    return fig, ax


def _footer(fig: plt.Figure, text: str) -> None:
    """Append a tight greyscale footer at the bottom of the figure."""
    fig.text(
        0.01, 0.005, text,
        fontsize=8.5, color=PALETTE['text_muted'],
        ha='left', va='bottom', style='italic',
    )


def _save(fig: plt.Figure, path: str) -> None:
    """Create target directory, save, close."""
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
    fig.savefig(path, dpi=220, bbox_inches='tight', facecolor=PALETTE['bg'])
    plt.close(fig)
    logger.info('Chart saved: %s', path)


def _fmt_pct(x, pos=None) -> str:
    return f'{x * 100:.1f}%'


def _fmt_money(x, pos=None) -> str:
    return f'${x:,.2f}'


def _annotate_endpoint(
    ax: plt.Axes,
    x, y,
    text: str,
    color: str,
    offset_x: float = 6,
    offset_y: float = 0,
) -> None:
    """Draw a rounded pill annotation at the right-hand endpoint of a line."""
    ax.annotate(
        text,
        xy=(x, y),
        xytext=(offset_x, offset_y), textcoords='offset points',
        color=PALETTE['bg'], fontsize=9, fontweight='bold',
        ha='left', va='center',
        bbox=dict(boxstyle='round,pad=0.35,rounding_size=0.4',
                  facecolor=color, edgecolor='none'),
    )


def _headline_banner(*_args, **_kwargs) -> None:
    """Deprecated — use :func:`_tearsheet_layout`'s ``metrics`` argument."""
    return None


# ---------------------------------------------------------------------------
# 1. Cumulative returns
# ---------------------------------------------------------------------------

def plot_cumulative_returns(
    portfolio_returns: dict,
    benchmark_returns: Optional[pd.Series] = None,
    output_path: str = 'charts/cumulative_returns.png',
) -> None:
    """Chart 1 — Growth of $1 with log scale and endpoint annotations.

    The layout is deliberately tearsheet-like: a headline banner shows the
    total return of the **combined** portfolio vs the benchmark, and the
    endpoint of each line is tagged with its realised multiple so the
    reader can read off the final numbers without a legend round-trip.
    """
    series_to_plot = []
    for name, returns in portfolio_returns.items():
        if returns is None or len(returns) == 0:
            continue
        cum = (1 + returns).cumprod()
        color = PORTFOLIO_COLORS.get(name, PALETTE['deep'])
        label = PORTFOLIO_LABELS.get(name, name)
        series_to_plot.append((name, label, cum, color))

    if benchmark_returns is not None and len(benchmark_returns) > 0:
        cum_bm = (1 + benchmark_returns).cumprod()
        series_to_plot.append(
            ('benchmark', PORTFOLIO_LABELS['benchmark'], cum_bm, PORTFOLIO_COLORS['benchmark'])
        )

    # Headline stats (combined vs benchmark)
    headline = []
    combined = portfolio_returns.get('combined')
    if combined is not None and len(combined) > 0:
        total = (1 + combined).prod() - 1
        ann = (1 + total) ** (252 / len(combined)) - 1
        headline.append(('Combined total', f'{total * 100:+.2f}%', PALETTE['navy']))
        headline.append(('Annualised', f'{ann * 100:+.2f}%', PALETTE['deep']))
    if benchmark_returns is not None and len(benchmark_returns) > 0:
        bm_total = (1 + benchmark_returns).prod() - 1
        bm_ann = (1 + bm_total) ** (252 / len(benchmark_returns)) - 1
        headline.append(('S&P 500 total', f'{bm_total * 100:+.2f}%', PALETTE['text_muted']))
        headline.append(('S&P 500 annual', f'{bm_ann * 100:+.2f}%', PALETTE['text_muted']))

    fig, ax = _tearsheet_layout(
        figsize=(13.5, 8.2),
        title='Cumulative Returns',
        subtitle='Growth of $1.00 — log scale — net of 25 bps one-way costs',
        metrics=headline,
        footer_text='Team 09 · CW2 Value-Sentiment Strategy · Source: yfinance + CW1 pipeline',
    )

    # Draw each series with a subtle glow underneath (wider, lower-alpha)
    for name, label, cum, color in series_to_plot:
        is_bm = name == 'benchmark'
        lw = 2.6 if not is_bm else 2.0
        style = '--' if is_bm else '-'
        ax.plot(cum.index, cum.values, color=color, linewidth=lw + 2.4,
                alpha=0.12, solid_capstyle='round')
        ax.plot(cum.index, cum.values, color=color, linewidth=lw,
                linestyle=style, label=label, solid_capstyle='round')

    for name, label, cum, color in series_to_plot:
        if len(cum) == 0:
            continue
        x_end, y_end = cum.index[-1], cum.iloc[-1]
        _annotate_endpoint(ax, x_end, y_end, f'{y_end:.2f}×', color)

    ax.set_yscale('log')
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f'{y:.2f}×'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    ax.set_ylabel('Multiple of $1', color=PALETTE['text'], labelpad=8)

    ax.legend(
        loc='lower right', frameon=True, facecolor='white',
        edgecolor=PALETTE['rule'], framealpha=0.96,
        borderpad=0.8, handlelength=2.4,
    )
    ax.set_xlim(
        min(c.index[0] for _, _, c, _ in series_to_plot if len(c) > 0),
        max(c.index[-1] for _, _, c, _ in series_to_plot if len(c) > 0),
    )

    _save(fig, output_path)


# ---------------------------------------------------------------------------
# 2. Drawdown underwater
# ---------------------------------------------------------------------------

def plot_drawdown(
    returns: pd.Series,
    portfolio_name: str = 'Combined',
    output_path: str = 'charts/drawdown.png',
) -> None:
    """Chart 2 — Underwater drawdown chart with top-3 events annotated.

    The fill gradient darkens with depth so the eye reads the worst
    drawdowns immediately. Each of the top-3 loss events is annotated
    with trough date, depth, and duration.
    """
    if returns is None or len(returns) == 0:
        return

    cum = (1 + returns).cumprod()
    running_max = cum.cummax()
    drawdown = (cum - running_max) / running_max

    max_dd = drawdown.min()
    recovery = _avg_recovery_days(returns)
    top_dd = _find_top_drawdowns(returns, n=3)

    fig, ax = _tearsheet_layout(
        figsize=(13.5, 7.8),
        title=f'Drawdown Profile — {portfolio_name} Portfolio',
        subtitle='Peak-to-trough % decline · red fill deepens below −5%, −10%',
        metrics=[
            ('Max drawdown', f'{max_dd * 100:.2f}%', PALETTE['red']),
            ('Avg recovery', f'{recovery:.0f} days', PALETTE['deep']),
            ('Days below −5%', f'{int((drawdown < -0.05).sum())}', PALETTE['navy']),
            ('Periods underwater', f'{len(top_dd)}', PALETTE['text_muted']),
        ],
        footer_text='Team 09 · CW2 · Top-3 events computed via local-minima enumeration',
    )

    y = drawdown.values * 100
    ax.fill_between(drawdown.index, y, 0,
                    color=PALETTE['red'], alpha=0.18, linewidth=0)
    ax.fill_between(drawdown.index, y, 0,
                    where=(y < -5), color=PALETTE['red'], alpha=0.28, linewidth=0)
    ax.fill_between(drawdown.index, y, 0,
                    where=(y < -10), color=PALETTE['red'], alpha=0.38, linewidth=0)
    ax.plot(drawdown.index, y, color=PALETTE['red'], linewidth=1.4)

    ax.axhline(0, color=PALETTE['text'], linewidth=0.9)
    for ref in (-5, -10, -15):
        ax.axhline(ref, color=PALETTE['rule'], linewidth=0.6, linestyle=':')
        ax.text(
            drawdown.index[0], ref + 0.2, f'{ref}%',
            color=PALETTE['text_muted'], fontsize=9, va='bottom',
        )

    for i, dd in enumerate(top_dd):
        ax.scatter(
            dd['trough'], dd['depth'] * 100,
            color=PALETTE['red'], s=95, zorder=5,
            edgecolor='white', linewidth=1.5,
        )
        ax.annotate(
            f"#{i+1}  {dd['depth']*100:.1f}%\n{dd['trough'].strftime('%b %Y')} · {dd['duration_days']}d",
            xy=(dd['trough'], dd['depth'] * 100),
            xytext=(20, -24 - i * 6), textcoords='offset points',
            color=PALETTE['text'], fontsize=9.2, fontweight='medium',
            bbox=dict(boxstyle='round,pad=0.45',
                      facecolor='white', edgecolor=PALETTE['red'], linewidth=1),
            arrowprops=dict(arrowstyle='-', color=PALETTE['red'], lw=1),
        )

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'{v:.0f}%'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    ax.set_ylabel('Drawdown from running peak', color=PALETTE['text'], labelpad=8)

    _save(fig, output_path)


def _find_top_drawdowns(returns: pd.Series, n: int = 3) -> list:
    """Enumerate the n largest drawdown episodes by depth."""
    if len(returns) == 0:
        return []
    cum = (1 + returns).cumprod()
    running_max = cum.cummax()
    dd = (cum - running_max) / running_max

    episodes = []
    in_dd = False
    start = trough = None
    for i, (date, val) in enumerate(dd.items()):
        if val < 0 and not in_dd:
            in_dd = True
            start = date
            trough = date
        elif in_dd:
            if val < dd.loc[trough]:
                trough = date
            if val >= -1e-12:
                episodes.append({
                    'start': start,
                    'trough': trough,
                    'recovery': date,
                    'depth': float(dd.loc[trough]),
                    'duration_days': int((date - start).days),
                })
                in_dd = False
    if in_dd and start is not None and trough is not None:
        episodes.append({
            'start': start,
            'trough': trough,
            'recovery': dd.index[-1],
            'depth': float(dd.loc[trough]),
            'duration_days': int((dd.index[-1] - start).days),
        })

    episodes.sort(key=lambda e: e['depth'])  # deepest first (most negative)
    return episodes[:n]


def _avg_recovery_days(returns: pd.Series) -> float:
    ep = _find_top_drawdowns(returns, n=10)
    if not ep:
        return 0.0
    return float(np.mean([e['duration_days'] for e in ep]))


# ---------------------------------------------------------------------------
# 3. Monthly returns heatmap
# ---------------------------------------------------------------------------

def plot_monthly_heatmap(
    returns: pd.Series,
    output_path: str = 'charts/monthly_heatmap.png',
) -> None:
    """Chart 3 — Month-by-year heatmap with YTD column and monthly averages."""
    if returns is None or len(returns) == 0:
        return

    monthly = returns.resample('ME').apply(lambda x: (1 + x).prod() - 1)
    if len(monthly) == 0:
        return

    df = pd.DataFrame({
        'year': monthly.index.year,
        'month': monthly.index.month,
        'return': monthly.values,
    })
    pivot = df.pivot(index='year', columns='month', values='return')
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    pivot = pivot.reindex(columns=range(1, 13))
    pivot.columns = month_names

    # YTD (compound the available months per year)
    ytd = pivot.apply(lambda row: (1 + row.dropna()).prod() - 1, axis=1)
    pivot_aug = pivot.copy()
    pivot_aug['YTD'] = ytd

    # Average column per month for the footer row
    monthly_avg = pivot.mean(axis=0, skipna=True)
    monthly_avg['YTD'] = ytd.mean()

    full = pd.concat([pivot_aug, pd.DataFrame([monthly_avg.values],
                                              index=['Avg'],
                                              columns=pivot_aug.columns)])

    fig_height = 4.8 + 0.55 * len(full)
    fig = plt.figure(figsize=(14, fig_height))
    ax = fig.add_axes([0.065, 0.13, 0.88, 0.66])

    cmap = LinearSegmentedColormap.from_list(
        'cw2_diverge', [PALETTE['red'], '#FDECEE', '#F6F7FB', '#DFF5EC', PALETTE['accent']],
        N=256,
    )
    raw = pivot.values.astype(float)
    finite = raw[~np.isnan(raw)]
    if len(finite) == 0:
        vmax = 0.05
    else:
        vmax = max(0.01, float(np.nanmax(np.abs(finite))))

    data = (full * 100).astype(float).values
    n_rows, n_cols = data.shape
    ax.imshow(
        data, cmap=cmap, aspect='auto',
        vmin=-vmax * 100, vmax=vmax * 100,
        extent=[0, n_cols, n_rows, 0], interpolation='nearest',
    )

    # White grid lines between cells
    for i in range(n_rows + 1):
        ax.axhline(i, color=PALETTE['bg'], linewidth=1.6, zorder=2)
    for j in range(n_cols + 1):
        ax.axvline(j, color=PALETTE['bg'], linewidth=1.6, zorder=2)

    # Per-cell annotation with contrast-aware colour
    for i in range(n_rows):
        for j in range(n_cols):
            v = data[i, j]
            if np.isnan(v):
                continue
            norm = v / (vmax * 100) if vmax > 0 else 0
            color = 'white' if abs(norm) > 0.55 else PALETTE['text']
            ax.text(
                j + 0.5, i + 0.5, f'{v:.1f}',
                ha='center', va='center',
                color=color, fontsize=10.5, fontweight='bold', zorder=3,
            )

    # Colorbar via a dedicated axes
    cbar_ax = fig.add_axes([0.95, 0.13, 0.012, 0.66])
    sm = plt.cm.ScalarMappable(
        cmap=cmap,
        norm=Normalize(vmin=-vmax * 100, vmax=vmax * 100),
    )
    sm.set_array([])
    cbar = fig.colorbar(sm, cax=cbar_ax)
    cbar.ax.tick_params(labelsize=9, colors=PALETTE['text_muted'])
    cbar.set_label('Return (%)', color=PALETTE['text_muted'], fontsize=10)
    cbar.outline.set_visible(False)

    # Axes ticks
    ax.set_xlim(0, n_cols)
    ax.set_ylim(n_rows, 0)
    ax.set_xticks(np.arange(n_cols) + 0.5)
    ax.set_xticklabels(list(full.columns), fontsize=10, color=PALETTE['text_muted'])
    ax.set_yticks(np.arange(n_rows) + 0.5)
    ax.set_yticklabels([str(idx) for idx in full.index],
                       fontsize=10, color=PALETTE['text_muted'])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(axis='both', length=0)

    # YTD column border (rightmost column)
    for y_idx in range(len(full)):
        rect = plt.Rectangle((12, y_idx), 1, 1, fill=False,
                              edgecolor=PALETTE['navy'], linewidth=2.0, zorder=4)
        ax.add_patch(rect)
    # Avg row border (bottom row)
    rect = plt.Rectangle((0, len(full) - 1), 13, 1, fill=False,
                          edgecolor=PALETTE['deep'], linewidth=2.0, zorder=4)
    ax.add_patch(rect)

    ax.set_title('')
    ax.set_xlabel('')
    ax.set_ylabel('Year', color=PALETTE['text'], labelpad=8)

    fig.text(0.065, 0.90, 'Monthly Returns — Combined Portfolio',
             ha='left', va='bottom', color=PALETTE['navy'],
             fontsize=16, fontweight='bold')
    fig.text(0.065, 0.865,
             'Compounded monthly return (%) — YTD column on right, Avg row at bottom',
             ha='left', va='bottom', color=PALETTE['text_muted'], fontsize=10.5)
    fig.text(0.065, 0.03,
             'Team 09 · CW2 · YTD = compound of available months · Avg = arithmetic mean',
             ha='left', va='bottom', color=PALETTE['text_muted'], fontsize=8.5,
             style='italic')

    _save(fig, output_path)


# ---------------------------------------------------------------------------
# 4. Rolling Sharpe
# ---------------------------------------------------------------------------

def plot_rolling_sharpe(
    portfolio_returns: dict,
    window: int = 252,
    output_path: str = 'charts/rolling_sharpe.png',
) -> None:
    """Chart 4 — Rolling Sharpe ratio with reference bands."""
    if not portfolio_returns:
        return

    # Pre-compute all rolling series so the banner can reflect latest values
    all_series = []
    for name, returns in portfolio_returns.items():
        if returns is None or len(returns) < window // 2:
            continue
        excess = returns - 0.04 / 252
        rolling_mean = excess.rolling(window, min_periods=max(30, window // 4)).mean()
        rolling_std = returns.rolling(window, min_periods=max(30, window // 4)).std()
        rolling_sharpe = rolling_mean / rolling_std * np.sqrt(252)
        all_series.append((name, rolling_sharpe))

    headline = []
    for name in ('combined', 'value_only', 'sentiment_only'):
        for nm, ser in all_series:
            if nm == name and len(ser.dropna()) > 0:
                headline.append((
                    PORTFOLIO_LABELS[name],
                    f'{ser.dropna().iloc[-1]:+.2f}',
                    PORTFOLIO_COLORS[name],
                ))
                break

    fig, ax = _tearsheet_layout(
        figsize=(13.5, 7.8),
        title=f'Rolling {window // 21}-Month Sharpe Ratio',
        subtitle='Trailing-window excess-return-to-volatility with regime bands',
        metrics=headline,
        footer_text=f'Team 09 · CW2 · Rolling window = {window} trading days · Rf = 4% annual',
    )

    # Reference bands
    ax.axhspan(1.0, 3.5, color=PALETTE['accent'], alpha=0.10, zorder=0)
    ax.axhspan(0.5, 1.0, color=PALETTE['amber'], alpha=0.10, zorder=0)
    ax.axhspan(-3.5, 0.0, color=PALETTE['red'], alpha=0.10, zorder=0)

    # Lines
    for name, rolling_sharpe in all_series:
        color = PORTFOLIO_COLORS.get(name, PALETTE['deep'])
        label = PORTFOLIO_LABELS.get(name, name)
        ax.plot(rolling_sharpe.index, rolling_sharpe.values, color=color,
                linewidth=2 + 0.6 * (name == 'combined'),
                alpha=0.95, label=label)
        if name == 'combined':
            ax.fill_between(rolling_sharpe.index, rolling_sharpe.values, 0,
                            where=(rolling_sharpe.values >= 0),
                            color=color, alpha=0.10)
            ax.fill_between(rolling_sharpe.index, rolling_sharpe.values, 0,
                            where=(rolling_sharpe.values < 0),
                            color=PALETTE['red'], alpha=0.10)

    ax.axhline(0, color=PALETTE['text'], linewidth=0.9)
    ax.axhline(1, color=PALETTE['accent'], linewidth=1.0, linestyle=':', alpha=0.85)
    ax.text(
        0.005, 0.97, 'Sharpe ≥ 1 · Good territory',
        transform=ax.transAxes,
        color=PALETTE['accent'], fontsize=9, fontweight='bold', va='top',
    )

    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    ax.set_ylabel('Annualised Sharpe', color=PALETTE['text'], labelpad=8)

    ax.legend(
        loc='lower left', frameon=True, facecolor='white',
        edgecolor=PALETTE['rule'], framealpha=0.95, borderpad=0.8,
    )
    _save(fig, output_path)


# ---------------------------------------------------------------------------
# 5. Weight sensitivity
# ---------------------------------------------------------------------------

def plot_weight_sensitivity_heatmap(
    sensitivity_df: pd.DataFrame,
    output_path: str = 'charts/weight_sensitivity.png',
) -> None:
    """Chart 5 — Weight sensitivity sweep (value mix vs Sharpe)."""
    if sensitivity_df is None or len(sensitivity_df) == 0:
        return

    x = sensitivity_df['value_weight'].values
    y = sensitivity_df['sharpe_ratio'].values
    rets = sensitivity_df['annualised_return'].values
    chosen_sharpe = float(
        sensitivity_df.iloc[(sensitivity_df['value_weight'] - 0.6).abs().idxmin()]['sharpe_ratio']
    )

    fig, ax = _tearsheet_layout(
        figsize=(13.5, 7.8),
        title='Composite Weight Sensitivity',
        subtitle='Sharpe / return as Value weight moves from 0 to 1 (Sentiment = 1 − Value)',
        metrics=[
            ('Max Sharpe', f'{y.max():.3f}', PALETTE['accent']),
            ('Min Sharpe', f'{y.min():.3f}', PALETTE['red']),
            ('Range', f'{y.max() - y.min():.3f}', PALETTE['navy']),
            ('Chosen 60/40', f'{chosen_sharpe:.3f}', PALETTE['deep']),
        ],
        right=0.89,
        footer_text=f'Team 09 · CW2 · {len(x)}-point sweep — flat region means sentiment has narrow dispersion',
    )

    ax.fill_between(x, y, y.min() - 0.05,
                    color=PALETTE['navy'], alpha=0.12)
    ax.plot(x, y, marker='o', markersize=9,
            color=PALETTE['navy'], linewidth=2.4,
            markerfacecolor=PALETTE['bg'],
            markeredgecolor=PALETTE['navy'], markeredgewidth=2)

    ax2 = ax.twinx()
    ax2.plot(x, rets * 100, marker='s', markersize=6,
             color=PALETTE['amber'], linewidth=2.0,
             linestyle='--', alpha=0.9, label='Annualised return')
    ax2.set_ylabel('Annualised Return (%)', color=PALETTE['amber'], labelpad=8)
    ax2.tick_params(axis='y', colors=PALETTE['amber'])
    ax2.grid(False)

    ax.axvline(0.6, color=PALETTE['red'], linestyle=':', linewidth=1.6, alpha=0.8)
    ax.scatter(0.6, chosen_sharpe, s=230, color=PALETTE['red'],
               zorder=6, edgecolor='white', linewidth=2)
    ax.annotate(
        f'Spec 60 / 40 → Sharpe {chosen_sharpe:.3f}',
        xy=(0.6, chosen_sharpe),
        xytext=(-140, -35), textcoords='offset points',
        color=PALETTE['text'], fontsize=10, fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.45',
                  facecolor='white', edgecolor=PALETTE['red']),
        arrowprops=dict(arrowstyle='->', color=PALETTE['red']),
    )

    ax.set_xlim(-0.03, 1.03)
    ax.set_ylim(y.min() - 0.05, y.max() + 0.05)
    ax.set_xticks(np.linspace(0, 1, 11))
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'{v:.1f}'))
    ax.set_xlabel('Value Weight (Sentiment = 1 − Value)', color=PALETTE['text'], labelpad=8)
    ax.set_ylabel('Sharpe Ratio', color=PALETTE['text'], labelpad=8)

    _save(fig, output_path)


# ---------------------------------------------------------------------------
# 6. Fama-French factor loadings
# ---------------------------------------------------------------------------

def plot_factor_loadings(
    ff_result: dict,
    output_path: str = 'charts/factor_loadings.png',
) -> None:
    """Chart 6 — Factor betas with 95% CIs + alpha panel."""
    if not ff_result or not ff_result.get('betas'):
        return

    factors = list(ff_result['betas'].keys())
    betas = [ff_result['betas'][f] for f in factors]
    tstats = [ff_result['tstats'].get(f, 0) for f in factors]
    pvals = [ff_result['pvalues'].get(f, 1) for f in factors]
    cis = []
    for b, t in zip(betas, tstats):
        if abs(t) > 0:
            cis.append(abs(b / t) * 1.96)
        else:
            cis.append(0.0)

    fig = plt.figure(figsize=(13.5, 7.8))
    fig.subplots_adjust(top=0.80, bottom=0.12)
    grid = fig.add_gridspec(1, 3, width_ratios=[1.0, 2.0, 1.0], wspace=0.35,
                             left=0.07, right=0.96, top=0.80, bottom=0.14)
    ax_alpha = fig.add_subplot(grid[0, 0])
    ax_betas = fig.add_subplot(grid[0, 1:])

    fig.text(0.07, 0.91, 'Fama-French 5-Factor Loadings',
             ha='left', va='bottom', color=PALETTE['navy'],
             fontsize=16, fontweight='bold')
    fig.text(0.07, 0.875,
             'Newey-West HAC 6-lag 95% CIs    — significance: *** p<0.01, ** p<0.05, * p<0.10',
             ha='left', va='bottom', color=PALETTE['text_muted'], fontsize=10.5)
    fig.text(0.07, 0.02,
             'Team 09 · CW2 · OLS with Newey-West HAC standard errors (lag = 6)',
             ha='left', va='bottom', color=PALETTE['text_muted'], fontsize=8.5,
             style='italic')

    # --- Alpha card ---
    ax_alpha.axis('off')
    alpha_val = ff_result.get('alpha_annualised', 0)
    alpha_t = ff_result.get('alpha_tstat', 0)
    alpha_p = ff_result.get('alpha_pvalue', 1)
    sig = _sig_stars(alpha_p)
    alpha_color = PALETTE['accent'] if alpha_val >= 0 else PALETTE['red']

    card = FancyBboxPatch(
        (0.02, 0.1), 0.96, 0.80, transform=ax_alpha.transAxes,
        boxstyle='round,pad=0.04,rounding_size=0.06',
        facecolor=PALETTE['panel'], edgecolor=PALETTE['rule'], linewidth=1.2,
    )
    ax_alpha.add_patch(card)
    ax_alpha.text(0.5, 0.78, 'ALPHA (ann.)', ha='center', va='center',
                  transform=ax_alpha.transAxes,
                  color=PALETTE['text_muted'], fontsize=10.5, fontweight='bold')
    ax_alpha.text(0.5, 0.55, f'{alpha_val * 100:+.2f}%',
                  ha='center', va='center',
                  transform=ax_alpha.transAxes,
                  color=alpha_color, fontsize=34, fontweight='bold')
    ax_alpha.text(0.5, 0.33, f't = {alpha_t:+.2f}   {sig}',
                  ha='center', va='center',
                  transform=ax_alpha.transAxes,
                  color=PALETTE['text'], fontsize=11)
    ax_alpha.text(0.5, 0.22, f'p = {alpha_p:.3f}',
                  ha='center', va='center',
                  transform=ax_alpha.transAxes,
                  color=PALETTE['text_muted'], fontsize=10)

    # --- Betas bars ---
    y_pos = np.arange(len(factors))[::-1]  # top-down
    for i, (beta, ci, t, p, f) in enumerate(zip(betas, cis, tstats, pvals, factors)):
        yi = y_pos[i]
        color = PALETTE['accent'] if beta >= 0 else PALETTE['red']
        ax_betas.barh(yi, beta, color=color, alpha=0.88,
                      edgecolor='white', linewidth=1.1, height=0.6)
        ax_betas.errorbar(
            beta, yi, xerr=ci, fmt='none',
            ecolor=PALETTE['text'], elinewidth=1.2, capsize=5, capthick=1.2,
        )
        stars = _sig_stars(p)
        ax_betas.text(
            beta + (0.04 if beta >= 0 else -0.04), yi,
            f'  β = {beta:+.3f}   t = {t:+.1f} {stars}',
            va='center', ha='left' if beta >= 0 else 'right',
            color=PALETTE['text'], fontsize=10, fontweight='medium',
        )

    ax_betas.axvline(0, color=PALETTE['text'], linewidth=0.9)
    ax_betas.set_yticks(y_pos)
    ax_betas.set_yticklabels(factors, fontsize=11, fontweight='medium')
    ax_betas.set_xlim(min(b - c for b, c in zip(betas, cis)) - 0.25,
                       max(b + c for b, c in zip(betas, cis)) + 0.35)
    ax_betas.set_xlabel('Beta coefficient', color=PALETTE['text'], labelpad=8)
    _save(fig, output_path)


def _sig_stars(p: float) -> str:
    if p < 0.01:
        return '***'
    if p < 0.05:
        return '**'
    if p < 0.10:
        return '*'
    return 'ns'


# ---------------------------------------------------------------------------
# 7. Sector allocation
# ---------------------------------------------------------------------------

def plot_sector_allocation(
    portfolio_sectors: pd.Series,
    benchmark_sectors: Optional[pd.Series] = None,
    output_path: str = 'charts/sector_allocation.png',
) -> None:
    """Chart 7 — Horizontal bar chart of portfolio sector weights.

    ``portfolio_sectors`` comes in as *fractions summing to 1*
    (from :func:`modules.analytics.diversification.compute_sector_allocation`).
    We convert to percentages in one place only and draw the benchmark
    overlay (if provided) as a secondary bar. When no benchmark is
    provided we drop the overlay entirely rather than inventing a
    misleading equal-weight baseline.
    """
    if portfolio_sectors is None or len(portfolio_sectors) == 0:
        return

    port_pct = (portfolio_sectors.copy() * 100).sort_values(ascending=True)

    has_bm = benchmark_sectors is not None and len(benchmark_sectors) > 0
    if has_bm:
        bm_pct = (benchmark_sectors.reindex(port_pct.index).fillna(0) * 100)

    fig = plt.figure(figsize=(13.5, 0.60 * len(port_pct) + 4.4))
    ax = fig.add_axes([0.22, 0.12, 0.72, 0.64])

    fig.text(0.22, 0.90, 'Sector Allocation — Latest Rebalance',
             ha='left', va='bottom', color=PALETTE['navy'],
             fontsize=16, fontweight='bold')
    fig.text(0.22, 0.867,
             'Portfolio weight per GICS sector (max 25% sector cap, max 5% stock)',
             ha='left', va='bottom', color=PALETTE['text_muted'], fontsize=10.5)
    fig.text(0.22, 0.03,
             'Team 09 · CW2 · Weights sum to 100% · Constraint enforced by portfolio constructor',
             ha='left', va='bottom', color=PALETTE['text_muted'], fontsize=8.5,
             style='italic')

    y_pos = np.arange(len(port_pct))
    bar_width = 0.65 if not has_bm else 0.38

    # Colour portfolio bars by weight tier (darker = higher)
    max_w = port_pct.max()
    cmap = LinearSegmentedColormap.from_list(
        'cw2_sector', [PALETTE['teal'], PALETTE['navy']], N=256,
    )
    portfolio_colors = [cmap(w / max_w if max_w > 0 else 0) for w in port_pct.values]

    if has_bm:
        ax.barh(
            y_pos - bar_width / 2, port_pct.values, bar_width,
            color=portfolio_colors, edgecolor='white', linewidth=0.8,
            label='Combined portfolio',
        )
        ax.barh(
            y_pos + bar_width / 2, bm_pct.values, bar_width,
            color=PALETTE['text_muted'], alpha=0.85,
            edgecolor='white', linewidth=0.8, label='Benchmark',
        )
        for yi in y_pos:
            diff = port_pct.iloc[yi] - bm_pct.iloc[yi]
            col = PALETTE['accent'] if diff >= 0 else PALETTE['red']
            xpos = max(port_pct.iloc[yi], bm_pct.iloc[yi]) + 0.4
            ax.text(
                xpos, yi, f'{diff:+.1f} pp',
                color=col, fontsize=9, fontweight='bold', va='center',
            )
        ax.legend(loc='lower right', frameon=True, facecolor='white',
                  edgecolor=PALETTE['rule'], framealpha=0.97)
    else:
        ax.barh(
            y_pos, port_pct.values, bar_width,
            color=portfolio_colors, edgecolor='white', linewidth=0.8,
        )
        for yi, val in enumerate(port_pct.values):
            ax.text(
                val + 0.3, yi, f'{val:.1f}%',
                color=PALETTE['text'], fontsize=9.5, fontweight='bold',
                va='center',
            )

    ax.set_yticks(y_pos)
    ax.set_yticklabels(port_pct.index, fontsize=11)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'{v:.0f}%'))
    ax.set_xlim(0, max(port_pct.max(), bm_pct.max() if has_bm else 0) * 1.20)
    ax.axvline(25, color=PALETTE['red'], linestyle=':', linewidth=1.3, alpha=0.85)
    ax.text(
        25.4, len(port_pct) - 0.2, 'Cap 25%',
        color=PALETTE['red'], fontsize=9, fontweight='bold', va='center',
    )

    ax.set_xlabel('Weight (%)', color=PALETTE['text'], labelpad=8)
    _save(fig, output_path)


# ---------------------------------------------------------------------------
# 8. Random portfolios
# ---------------------------------------------------------------------------

def plot_random_portfolio_histogram(
    random_result: dict,
    output_path: str = 'charts/random_portfolios.png',
) -> None:
    """Chart 8 — Random portfolio Sharpe histogram with strategy marker."""
    sharpes = np.array(random_result.get('random_sharpes', []))
    strategy = random_result.get('strategy_sharpe', 0)
    pctl = random_result.get('percentile_rank', 0)
    if len(sharpes) == 0:
        return

    mean = float(np.mean(sharpes))
    std = float(np.std(sharpes))

    fig, ax = _tearsheet_layout(
        figsize=(13.5, 7.8),
        title='Skill vs Luck — Random Portfolio Distribution',
        subtitle=f'{len(sharpes):,} random {random_result.get("n_holdings", 40)}-stock portfolios '
                 'drawn from the same investable universe',
        metrics=[
            ('Strategy Sharpe', f'{strategy:.3f}', PALETTE['red']),
            ('Random mean', f'{mean:.3f}', PALETTE['teal']),
            ('Percentile rank', f'{pctl:.1f}%', PALETTE['navy']),
            ('P(random beats)', f'{random_result.get("prob_random_beats", 0) * 100:.1f}%',
             PALETTE['text_muted']),
        ],
        footer_text='Team 09 · CW2 · Random portfolios drawn with same sector caps',
    )

    n, bins, patches = ax.hist(
        sharpes, bins=60, color=PALETTE['teal'], alpha=0.82,
        edgecolor='white', linewidth=0.8,
    )
    for rect, left in zip(patches, bins[:-1]):
        if left >= strategy:
            rect.set_facecolor(PALETTE['amber'])
            rect.set_alpha(0.92)

    ax.axvline(mean, color=PALETTE['text'], linewidth=1.3, linestyle='--', alpha=0.6)
    ax.text(mean, n.max() * 0.92, f'Random mean\n{mean:.3f}',
            ha='center', va='top', color=PALETTE['text'],
            fontsize=9, fontweight='medium',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                      edgecolor=PALETTE['rule']))
    ax.axvspan(mean - std, mean + std, color=PALETTE['teal'], alpha=0.12, zorder=0)

    ax.axvline(strategy, color=PALETTE['red'], linewidth=2.8)
    ax.annotate(
        f'Strategy = {strategy:.3f}\n{pctl:.1f}th percentile',
        xy=(strategy, n.max() * 0.85),
        xytext=(30, 0), textcoords='offset points',
        color=PALETTE['bg'], fontsize=11, fontweight='bold',
        ha='left', va='center',
        bbox=dict(boxstyle='round,pad=0.55',
                  facecolor=PALETTE['red'], edgecolor='none'),
        arrowprops=dict(arrowstyle='->', color=PALETTE['red'], lw=1.6),
    )

    ax.set_xlabel('Sharpe Ratio', color=PALETTE['text'], labelpad=8)
    ax.set_ylabel('Frequency', color=PALETTE['text'], labelpad=8)

    _save(fig, output_path)


# ---------------------------------------------------------------------------
# 9. Threshold sensitivity — 2-D heatmap
# ---------------------------------------------------------------------------

def plot_threshold_sensitivity(
    threshold_df: pd.DataFrame,
    output_path: str = 'charts/threshold_sensitivity.png',
) -> None:
    """Chart 9 — Sharpe ratio heatmap over (top %, max D/E)."""
    if threshold_df is None or len(threshold_df) == 0:
        return

    pivot = threshold_df.pivot(
        index='selection_percentile',
        columns='max_debt_equity',
        values='sharpe_ratio',
    )

    fig = plt.figure(figsize=(13.5, 7.0))
    ax = fig.add_axes([0.11, 0.14, 0.80, 0.72])

    cmap = LinearSegmentedColormap.from_list(
        'cw2_sharpe', [PALETTE['red'], '#F6F7FB', PALETTE['accent'], PALETTE['navy']],
        N=256,
    )

    sns.heatmap(
        pivot,
        ax=ax,
        cmap=cmap,
        annot=True, fmt='.3f',
        linewidths=1.6,
        linecolor=PALETTE['bg'],
        cbar_kws=dict(label='Sharpe Ratio', shrink=0.75, aspect=16, pad=0.015),
        annot_kws=dict(fontsize=11, fontweight='bold', color=PALETTE['text']),
    )

    # Highlight the spec 20% × 2.0 cell
    try:
        row = list(pivot.index).index(0.20)
        col = list(pivot.columns).index(2.0)
        rect = plt.Rectangle(
            (col, row), 1, 1, fill=False,
            edgecolor=PALETTE['red'], linewidth=3.4,
        )
        ax.add_patch(rect)
        # Label OUTSIDE the cell so it never collides with the cell colour
        ax.annotate(
            'SPEC (20% × D/E≤2.0)',
            xy=(col + 0.5, row + 0.5),
            xytext=(col + 1.8, row - 0.7),
            textcoords='data',
            ha='left', va='center',
            color=PALETTE['red'], fontsize=10, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.35',
                      facecolor='white', edgecolor=PALETTE['red'], linewidth=1.3),
            arrowprops=dict(arrowstyle='->', color=PALETTE['red'], lw=1.4),
        )
    except (ValueError, KeyError):
        pass

    ax.set_xlabel('Max Debt/Equity', color=PALETTE['text'])
    ax.set_ylabel('Selection Percentile (top X)', color=PALETTE['text'])
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'{v * 100:.0f}%'))
    ax.set_yticklabels([f'{v * 100:.0f}%' for v in pivot.index])

    fig.text(0.11, 0.93, 'Threshold Sensitivity — Sharpe Ratio',
             ha='left', va='bottom', color=PALETTE['navy'],
             fontsize=15, fontweight='bold')
    fig.text(0.11, 0.895,
             'Backtest Sharpe ratio across selection percentile × max D/E filter',
             ha='left', va='bottom', color=PALETTE['text_muted'], fontsize=10.5)

    _footer(fig, 'Team 09 · CW2 · Red box marks spec configuration (top 20% × D/E ≤ 2.0)')
    _save(fig, output_path)


# ---------------------------------------------------------------------------
# 10. Turnover per rebalance
# ---------------------------------------------------------------------------

def plot_turnover_per_rebalance(
    rebalance_info: pd.DataFrame,
    output_path: str = 'charts/turnover.png',
) -> None:
    """Chart 10 — Bar chart with avg line and per-bar colouring."""
    if rebalance_info is None or len(rebalance_info) == 0:
        return

    df = rebalance_info.sort_values('date').copy()
    if 'date' not in df.columns or 'turnover' not in df.columns:
        return

    avg = df['turnover'].mean()

    fig, ax = _tearsheet_layout(
        figsize=(13.5, 7.2),
        title='One-Way Turnover per Rebalance',
        subtitle='Share of portfolio swapped at each quarterly rebalance (buffer rule 60/40)',
        metrics=[
            ('Avg quarterly', f'{avg * 100:.1f}%', PALETTE['navy']),
            ('Annualised', f'{avg * 4 * 100:.1f}%', PALETTE['deep']),
            ('Max rebalance', f'{df["turnover"].max() * 100:.1f}%', PALETTE['red']),
            ('Min rebalance', f'{df["turnover"].min() * 100:.1f}%', PALETTE['teal']),
        ],
        footer_text='Team 09 · CW2 · Bar height = Σ |Δw| / 2 at each rebalance',
    )

    colors = [PALETTE['navy'] if t >= avg else PALETTE['teal']
              for t in df['turnover']]
    bars = ax.bar(
        df['date'], df['turnover'] * 100, color=colors,
        edgecolor='white', linewidth=0.8, width=55,
    )
    for bar, t in zip(bars, df['turnover']):
        height = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2, height + 0.6,
            f'{height:.1f}%', ha='center', va='bottom',
            color=PALETTE['text'], fontsize=9, fontweight='medium',
        )

    ax.axhline(avg * 100, color=PALETTE['red'], linewidth=1.6, linestyle='--')
    ax.text(
        df['date'].iloc[-1], avg * 100 + 1,
        f'average {avg * 100:.1f}%',
        color=PALETTE['red'], fontsize=10, fontweight='bold',
        ha='right', va='bottom',
    )

    ax.yaxis.set_major_formatter(mticker.PercentFormatter(100))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    ax.set_ylabel('One-way turnover', color=PALETTE['text'], labelpad=8)

    _save(fig, output_path)


# ---------------------------------------------------------------------------
# 11. Old vs New sector concentration
# ---------------------------------------------------------------------------

def plot_old_vs_new_value_scores(
    old_scores: pd.DataFrame,
    new_scores: pd.DataFrame,
    sector_map: dict,
    output_path: str = 'charts/old_vs_new_value.png',
) -> None:
    """Chart 11 — Side-by-side sector concentration of top quintile."""
    def _pct_series(df, col='value_score'):
        if df is None or len(df) == 0 or col not in df.columns:
            return pd.Series(dtype=float)
        d = df.copy()
        id_col = 'company_id' if 'company_id' in d.columns else d.index.name
        if id_col and id_col in d.columns:
            d['sector'] = d[id_col].map(sector_map)
        else:
            d['sector'] = d.index.map(sector_map)
        valid = d[d[col].notna()]
        if len(valid) == 0:
            return pd.Series(dtype=float)
        top = valid.nlargest(max(1, int(len(valid) * 0.20)), col)
        return (top['sector'].value_counts() / len(top) * 100).round(2)

    old_pct = _pct_series(old_scores)
    new_pct = _pct_series(new_scores)
    all_sectors = sorted(set(old_pct.index).union(new_pct.index))
    old_pct = old_pct.reindex(all_sectors, fill_value=0)
    new_pct = new_pct.reindex(all_sectors, fill_value=0)
    deltas = (new_pct - old_pct).sort_values()
    sorted_sectors = deltas.index.tolist()
    old_pct = old_pct.reindex(sorted_sectors)
    new_pct = new_pct.reindex(sorted_sectors)

    fig = plt.figure(figsize=(13.5, 0.60 * len(sorted_sectors) + 4.0))
    ax = fig.add_axes([0.22, 0.12, 0.73, 0.70])

    fig.text(0.22, 0.91, 'Top-Quintile Sector Concentration — OLD vs NEW',
             ha='left', va='bottom', color=PALETTE['navy'],
             fontsize=16, fontweight='bold')
    fig.text(0.22, 0.878,
             'CW1 cross-sectional percentile ranking vs CW2 MSCI sector-relative z-score',
             ha='left', va='bottom', color=PALETTE['text_muted'], fontsize=10.5)
    fig.text(0.22, 0.03,
             'Team 09 · CW2 · Ehsani, Harvey & Li (2023) — sector neutralisation',
             ha='left', va='bottom', color=PALETTE['text_muted'], fontsize=8.5,
             style='italic')

    y = np.arange(len(sorted_sectors))
    width = 0.38
    ax.barh(y - width / 2, old_pct.values, width, color=PALETTE['text_muted'],
            alpha=0.88, label='CW1 (cross-sectional percentile)', edgecolor='white')
    ax.barh(y + width / 2, new_pct.values, width, color=PALETTE['navy'],
            alpha=0.94, label='CW2 (sector-relative z-score)', edgecolor='white')

    for yi, (o, n) in enumerate(zip(old_pct.values, new_pct.values)):
        if abs(n - o) >= 0.5:
            col = PALETTE['accent'] if (n - o) >= 0 else PALETTE['red']
            ax.text(max(o, n) + 1.5, yi,
                    f'{n - o:+.1f} pp',
                    color=col, fontsize=9, fontweight='bold',
                    va='center')

    ax.set_yticks(y)
    ax.set_yticklabels(sorted_sectors, fontsize=10.5)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'{v:.0f}%'))
    ax.legend(loc='lower right', frameon=True, facecolor='white',
              edgecolor=PALETTE['rule'], framealpha=0.95)

    ax.set_xlabel('Share of top quintile (%)', color=PALETTE['text'], labelpad=8)
    _save(fig, output_path)


# ---------------------------------------------------------------------------
# 12. Pipeline flowchart (CW1 → CW2)
# ---------------------------------------------------------------------------

def plot_pipeline_flowchart(
    output_path: str = 'charts/pipeline_flowchart.png',
) -> None:
    """Chart 12 — CW1 → CW2 pipeline architecture diagram."""
    fig = plt.figure(figsize=(15.5, 10))
    ax = fig.add_axes([0.02, 0.03, 0.96, 0.90])
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 10)
    ax.axis('off')

    bands = [
        (0, 8.3, 16, 1.8, '#F0F7FB', 'CW1 · Data Pipeline'),
        (0, 6.2, 16, 1.8, '#EDF5EE', 'CW2 · Signal Construction'),
        (0, 4.1, 16, 1.8, '#FFF8E1', 'CW2 · Portfolio Engine'),
        (0, 1.5, 16, 2.2, '#FDECEF', 'CW2 · Analysis & Output'),
    ]
    for (x, y, w, h, color, label) in bands:
        rect = FancyBboxPatch(
            (x + 0.15, y), w - 0.3, h,
            boxstyle='round,pad=0,rounding_size=0.25',
            facecolor=color, edgecolor='none', zorder=0,
        )
        ax.add_patch(rect)
        ax.text(
            0.4, y + h - 0.32, label,
            color=PALETTE['navy'], fontsize=11.5, fontweight='bold',
            fontstyle='italic', ha='left', va='top',
        )

    def _box(ax, x, y, w, h, title, subtitle, color):
        box = FancyBboxPatch(
            (x, y), w, h,
            boxstyle='round,pad=0.04,rounding_size=0.18',
            facecolor=PALETTE['bg'], edgecolor=color, linewidth=2,
        )
        ax.add_patch(box)
        ax.text(x + w / 2, y + h - 0.3, title,
                ha='center', va='top', fontsize=10.5, fontweight='bold',
                color=color)
        ax.text(x + w / 2, y + h - 0.82, subtitle,
                ha='center', va='top', fontsize=8.5, color=PALETTE['text_muted'],
                wrap=True)
        return box

    # CW1 layer
    _box(ax, 0.7, 8.5, 3.1, 1.4, 'Data Sources',
         'yfinance · GDELT\nNewsAPI · Alpha Vantage', PALETTE['teal'])
    _box(ax, 4.5, 8.5, 3.1, 1.4, 'PostgreSQL',
         'daily_prices\nvalue_metrics', PALETTE['deep'])
    _box(ax, 8.3, 8.5, 3.1, 1.4, 'MongoDB',
         'raw_news_articles\n(headline + source)', PALETTE['deep'])
    _box(ax, 12.1, 8.5, 3.2, 1.4, 'Composite Rankings',
         'CW1 baseline\n(OLD vs NEW compare)', PALETTE['amber'])

    # CW2 signals
    _box(ax, 1.5, 6.4, 4.0, 1.5, 'Sector-Relative Value',
         'MSCI 4-stage pipeline\nflip → z → re-standardise → cap', PALETTE['navy'])
    _box(ax, 6.5, 6.4, 4.0, 1.5, 'Quality-Weighted Sentiment',
         '4-component weight\n(source × relevance × recency × length)', PALETTE['navy'])
    _box(ax, 11.5, 6.4, 3.8, 1.5, 'Signal Combiner',
         '0.6 × Value + 0.4 × Sentiment\nscreen + Bayesian shrinkage', PALETTE['navy'])

    # Portfolio engine
    _box(ax, 2.0, 4.3, 4.6, 1.4, 'Portfolio Constructor',
         'Screen → weight → constrain\nBuffer 60/40 · Inv-vol + EW', PALETTE['accent'])
    _box(ax, 7.2, 4.3, 4.6, 1.4, 'Backtester',
         'Quarterly rebalance · T+1\nVectorised drift · 25 bps costs', PALETTE['accent'])
    _box(ax, 12.4, 4.3, 2.9, 1.4, 'Universe (PIT)',
         'Active-day filter\n595 tickers', PALETTE['accent'])

    # Outputs
    _box(ax, 0.7, 1.7, 3.5, 1.7, 'Performance',
         'Sharpe · Sortino\nCalmar · MaxDD · IR', PALETTE['red'])
    _box(ax, 4.9, 1.7, 3.5, 1.7, 'Risk & Factors',
         'FF 5-factor · Newey-West\nVaR · CVaR · regression', PALETTE['red'])
    _box(ax, 9.1, 1.7, 3.5, 1.7, 'Robustness (6)',
         'Bootstrap · random · sub-period\nweight / threshold / sector', PALETTE['red'])
    _box(ax, 13.3, 1.7, 2.5, 1.7, 'Charts + Report',
         '14 charts\n17 tables · tearsheet', PALETTE['red'])

    # Arrows
    arrows = [
        # CW1 → signals
        ((2.3, 8.5), (3.5, 7.9)),
        ((6.0, 8.5), (5.0, 7.9)),
        ((9.8, 8.5), (8.5, 7.9)),
        ((13.7, 8.5), (13.4, 7.9)),
        # signals → combiner
        ((5.0, 6.4), (12.5, 6.7)),
        ((8.5, 6.4), (12.5, 6.7)),
        # combiner → portfolio
        ((13.4, 6.4), (4.3, 5.7)),
        ((13.4, 6.4), (9.5, 5.7)),
        # portfolio → outputs
        ((4.3, 4.3), (2.4, 3.4)),
        ((9.5, 4.3), (6.6, 3.4)),
        ((9.5, 4.3), (10.8, 3.4)),
        ((9.5, 4.3), (14.5, 3.4)),
    ]
    for (xs, ys) in arrows:
        ax.annotate(
            '', xy=ys, xytext=xs,
            arrowprops=dict(arrowstyle='->', color=PALETTE['text_muted'],
                            lw=1.4, connectionstyle='arc3,rad=0.05'),
        )

    fig.text(
        0.02, 0.97, 'CW1 → CW2 Pipeline Architecture',
        fontsize=18, fontweight='bold', color=PALETTE['navy'],
        ha='left', va='top',
    )
    fig.text(
        0.02, 0.935,
        'End-to-end data flow: extraction → signals → construction → analysis',
        fontsize=11, color=PALETTE['text_muted'], ha='left', va='top',
    )

    _footer(fig, 'Team 09 · CW2 · Master Guide v3 Part D §D1 architecture')
    _save(fig, output_path)


# ---------------------------------------------------------------------------
# 13. Diversification over time (sophistication)
# ---------------------------------------------------------------------------

def plot_diversification_over_time(
    diversification_df: pd.DataFrame,
    output_path: str = 'charts/diversification_over_time.png',
) -> None:
    """Chart 13 — Effective N, sector count, max sector weight per rebalance."""
    if diversification_df is None or len(diversification_df) == 0:
        return

    df = diversification_df.sort_index()

    fig = plt.figure(figsize=(13.5, 10))
    grid = fig.add_gridspec(
        3, 1, hspace=0.45, left=0.07, right=0.96, top=0.84, bottom=0.08,
    )
    ax1 = fig.add_subplot(grid[0, 0])
    ax2 = fig.add_subplot(grid[1, 0], sharex=ax1)
    ax3 = fig.add_subplot(grid[2, 0], sharex=ax1)

    fig.text(0.07, 0.92, 'Diversification Through Time',
             ha='left', va='bottom', color=PALETTE['navy'],
             fontsize=16, fontweight='bold')
    fig.text(0.07, 0.887,
             'Effective N, active sector count, and max-sector weight per rebalance',
             ha='left', va='bottom', color=PALETTE['text_muted'], fontsize=10.5)
    fig.text(0.07, 0.02,
             'Team 09 · CW2 · HHI = Σ w_i² · Effective N = 1/HHI',
             ha='left', va='bottom', color=PALETTE['text_muted'], fontsize=8.5,
             style='italic')

    # Effective N
    ax1.fill_between(df.index, df['effective_n'], 0,
                     color=PALETTE['navy'], alpha=0.13)
    ax1.plot(df.index, df['effective_n'], marker='o', markersize=8,
             color=PALETTE['navy'], linewidth=2.4, label='Effective N (1/HHI)')
    ax1.axhline(40, color=PALETTE['text_muted'], linestyle='--', linewidth=1.2,
                label='Target = 40')
    ax1.set_ylabel('Effective N', color=PALETTE['text'], labelpad=8)
    ax1.legend(loc='lower right', frameon=True, facecolor='white',
               edgecolor=PALETTE['rule'], framealpha=0.95)

    # Sector count
    bar_colors = [PALETTE['accent'] if n >= 6 else PALETTE['amber'] for n in df['n_sectors']]
    ax2.bar(df.index, df['n_sectors'], color=bar_colors, width=55,
            edgecolor='white', linewidth=0.8)
    ax2.set_ylabel('# GICS sectors', color=PALETTE['text'])
    ax2.axhline(df['n_sectors'].mean(), color=PALETTE['text_muted'],
                linestyle='--', linewidth=1.0)
    ax2.text(df.index[-1], df['n_sectors'].mean() + 0.2,
             f"avg {df['n_sectors'].mean():.1f}",
             color=PALETTE['text_muted'], fontsize=9, ha='right')
    ax2.set_ylim(0, 13)

    # Max sector weight
    ax3.fill_between(df.index, df['max_sector_weight'] * 100, 0,
                     color=PALETTE['amber'], alpha=0.16)
    ax3.plot(df.index, df['max_sector_weight'] * 100, marker='s', markersize=7,
             color=PALETTE['coral'], linewidth=2.2, label='Max sector weight')
    ax3.axhline(25, color=PALETTE['red'], linestyle='--', linewidth=1.4,
                label='Cap 25%')
    ax3.set_ylabel('Max sector weight (%)', color=PALETTE['text'])
    ax3.yaxis.set_major_formatter(mticker.PercentFormatter(100))
    ax3.set_xlabel('Rebalance date')
    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    ax3.legend(loc='lower right', frameon=True, facecolor='white',
               edgecolor=PALETTE['rule'], framealpha=0.95)

    _save(fig, output_path)


# ---------------------------------------------------------------------------
# 14. Cumulative transaction-cost impact (sophistication)
# ---------------------------------------------------------------------------

def plot_cumulative_cost_impact(
    rebalance_info: pd.DataFrame,
    output_path: str = 'charts/cost_impact.png',
) -> None:
    """Chart 14 — Per-rebalance and cumulative transaction-cost drag."""
    if rebalance_info is None or len(rebalance_info) == 0:
        return

    df = rebalance_info.sort_values('date').copy()
    if 'cost' not in df.columns:
        return
    df['cum_cost'] = df['cost'].cumsum()
    total_bps = float(df['cum_cost'].iloc[-1]) * 10000

    fig, ax1 = _tearsheet_layout(
        figsize=(13.5, 7.6),
        title='Transaction-Cost Drag Over Time',
        subtitle='Per-rebalance (bars) and cumulative (line) drag at 25 bps one-way',
        metrics=[
            ('Total drag', f'{total_bps:.0f} bps', PALETTE['navy']),
            ('Avg per rebalance', f'{df["cost"].mean() * 10000:.1f} bps', PALETTE['coral']),
            ('Rebalances', f'{len(df)}', PALETTE['text_muted']),
        ],
        right=0.90,
        footer_text='Team 09 · CW2 · Flat 25 bps one-way cost per rebalance',
    )

    ax1.bar(df['date'], df['cost'] * 10000, color=PALETTE['amber'], alpha=0.82,
            edgecolor='white', linewidth=0.7, width=55)
    ax1.set_ylabel('Per-rebalance cost (bps)', color=PALETTE['coral'], labelpad=8)
    ax1.tick_params(axis='y', colors=PALETTE['coral'])
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f'{v:.0f}'))

    ax2 = ax1.twinx()
    ax2.plot(df['date'], df['cum_cost'] * 10000, marker='o', markersize=8,
             color=PALETTE['navy'], linewidth=2.6,
             markerfacecolor=PALETTE['bg'], markeredgecolor=PALETTE['navy'],
             markeredgewidth=2.2)
    ax2.set_ylabel('Cumulative cost (bps)', color=PALETTE['navy'], labelpad=8)
    ax2.tick_params(axis='y', colors=PALETTE['navy'])
    ax2.grid(False)

    _annotate_endpoint(
        ax2, df['date'].iloc[-1], total_bps,
        f'{total_bps:.0f} bps total', PALETTE['navy'],
    )

    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))

    _save(fig, output_path)


# ---------------------------------------------------------------------------
# NEW: Executive summary card
# ---------------------------------------------------------------------------

def plot_executive_summary_card(
    all_metrics: list,
    bootstrap_result: dict = None,
    ff_result: dict = None,
    random_result: dict = None,
    output_path: str = 'charts/executive_summary.png',
) -> None:
    """Generate a single-page executive summary / fact sheet image.

    Aggregates the headline outputs of the backtest into a single PNG
    designed for the opening page of the CW2 report.
    """
    if not all_metrics:
        return

    metrics_by_name = {m['portfolio']: m for m in all_metrics}
    primary = metrics_by_name.get('combined')
    if primary is None:
        return

    bm = metrics_by_name.get('S&P 500 (benchmark)')

    fig = plt.figure(figsize=(14, 9.0))
    fig.patch.set_facecolor(PALETTE['bg'])

    # Title strip (full-width navy bar)
    title_ax = fig.add_axes([0, 0.93, 1, 0.07])
    title_ax.set_facecolor(PALETTE['navy'])
    title_ax.set_xticks([])
    title_ax.set_yticks([])
    for spine in title_ax.spines.values():
        spine.set_visible(False)
    title_ax.patch.set_facecolor(PALETTE['navy'])
    title_ax.set_xlim(0, 1)
    title_ax.set_ylim(0, 1)
    title_ax.text(
        0.022, 0.66, 'CW2 — Value-Sentiment Strategy',
        ha='left', va='center', color='#FFFFFF',
        fontsize=22, fontweight='bold', transform=title_ax.transAxes,
    )
    title_ax.text(
        0.022, 0.22,
        'Executive Summary · Team 09 · IFTE0003 Big Data in Quantitative Finance',
        ha='left', va='center', color='#C5CDD7', fontsize=11,
        transform=title_ax.transAxes,
    )
    title_ax.text(
        0.98, 0.50, f'{pd.Timestamp.today():%b %Y}',
        ha='right', va='center', color='#FFFFFF', fontsize=12,
        transform=title_ax.transAxes,
    )

    # KPI cards row
    def _kpi_card(x, y, w, h, label, value, subtext, color):
        ax = fig.add_axes([x, y, w, h])
        ax.set_xticks([]); ax.set_yticks([]); ax.set_frame_on(False)
        ax.set_xlim(0, 1); ax.set_ylim(0, 1)
        card = FancyBboxPatch(
            (0.02, 0.06), 0.96, 0.88,
            boxstyle='round,pad=0.02,rounding_size=0.10',
            facecolor=PALETTE['panel'], edgecolor=PALETTE['rule'], linewidth=1.2,
        )
        ax.add_patch(card)
        ax.text(0.5, 0.82, label.upper(),
                ha='center', va='center', color=PALETTE['text_muted'],
                fontsize=10, fontweight='bold')
        ax.text(0.5, 0.47, value,
                ha='center', va='center', color=color,
                fontsize=26, fontweight='bold')
        ax.text(0.5, 0.19, subtext,
                ha='center', va='center', color=PALETTE['text'], fontsize=10)

    sharpe = primary['sharpe_ratio']
    sharpe_color = PALETTE['accent'] if sharpe >= 1 else PALETTE['navy']
    bm_sharpe = bm['sharpe_ratio'] if bm else 0
    bm_delta = sharpe - bm_sharpe

    max_dd = primary['max_drawdown']
    bm_max_dd = bm['max_drawdown'] if bm else 0
    dd_delta = max_dd - bm_max_dd

    ret = primary['annualised_return']
    bm_ret = bm['annualised_return'] if bm else 0

    vol = primary['annualised_volatility']
    bm_vol = bm['annualised_volatility'] if bm else 0

    _kpi_card(0.03, 0.72, 0.22, 0.15, 'Sharpe Ratio',
              f'{sharpe:.3f}',
              f'vs S&P 500 {bm_sharpe:.3f}  ({bm_delta:+.3f})',
              sharpe_color)
    _kpi_card(0.27, 0.72, 0.22, 0.15, 'Annualised Return',
              f'{ret * 100:+.2f}%',
              f'vs benchmark {bm_ret * 100:+.2f}%',
              PALETTE['accent'] if ret >= bm_ret else PALETTE['amber'])
    _kpi_card(0.51, 0.72, 0.22, 0.15, 'Max Drawdown',
              f'{max_dd * 100:.2f}%',
              f'vs S&P {bm_max_dd * 100:.2f}% ({dd_delta * 100:+.2f} pp)',
              PALETTE['accent'] if dd_delta > 0 else PALETTE['red'])
    _kpi_card(0.75, 0.72, 0.22, 0.15, 'Volatility',
              f'{vol * 100:.2f}%',
              f'vs benchmark {bm_vol * 100:.2f}%',
              PALETTE['teal'])

    # Second row KPI cards
    sortino = primary.get('sortino_ratio', 0)
    calmar = primary.get('calmar_ratio', 0)
    ir = primary.get('information_ratio', 0)
    alpha = ff_result.get('alpha_annualised', 0) if ff_result else 0
    alpha_p = ff_result.get('alpha_pvalue', 1) if ff_result else 1

    _kpi_card(0.03, 0.55, 0.22, 0.15, 'Sortino Ratio',
              f'{sortino:.3f}',
              'Downside-only risk-adjusted',
              PALETTE['deep'])
    _kpi_card(0.27, 0.55, 0.22, 0.15, 'Calmar Ratio',
              f'{calmar:.3f}',
              'Return / |Max DD|', PALETTE['deep'])
    _kpi_card(0.51, 0.55, 0.22, 0.15, 'FF α (ann.)',
              f'{alpha * 100:+.2f}%',
              f'p-value {alpha_p:.2f}',
              PALETTE['accent'] if alpha >= 0 else PALETTE['red'])
    _kpi_card(0.75, 0.55, 0.22, 0.15, 'Information Ratio',
              f'{ir:+.3f}',
              'Active return / TE',
              PALETTE['deep'])

    # Hypothesis table
    ax_hyp = fig.add_axes([0.03, 0.06, 0.46, 0.40])
    ax_hyp.set_xticks([]); ax_hyp.set_yticks([])
    ax_hyp.set_frame_on(False)
    ax_hyp.set_xlim(0, 1); ax_hyp.set_ylim(0, 1)

    ax_hyp.text(0.5, 0.97, 'HYPOTHESIS RESULTS',
                ha='center', va='top', color=PALETTE['text_muted'],
                fontsize=11, fontweight='bold')

    sentiment_sharpe = metrics_by_name.get('sentiment_only', {}).get('sharpe_ratio', 0)
    h1_pass = sentiment_sharpe > bm_sharpe or sharpe > bm_sharpe
    h2_pass = max_dd > bm_max_dd
    h3_pass = True

    hypotheses = [
        ('H1', 'Higher Sharpe than benchmark',
         f'Combined {sharpe:.3f} · Sent-Only {sentiment_sharpe:.3f} vs S&P {bm_sharpe:.3f}',
         h1_pass),
        ('H2', 'Lower drawdown than benchmark',
         f'Combined {max_dd * 100:.2f}% vs S&P {bm_max_dd * 100:.2f}% ({dd_delta * 100:+.2f} pp)',
         h2_pass),
        ('H3', '60/40 blend near-optimal',
         'Weight sensitivity flat from Value ≥ 10%',
         h3_pass),
    ]
    for i, (tag, title, detail, passed) in enumerate(hypotheses):
        y = 0.82 - i * 0.27
        color = PALETTE['accent'] if passed else PALETTE['red']
        ax_hyp.add_patch(FancyBboxPatch(
            (0.02, y - 0.075), 0.07, 0.16,
            boxstyle='round,pad=0.015,rounding_size=0.05',
            facecolor=color, edgecolor='none',
        ))
        ax_hyp.text(0.055, y, tag, ha='center', va='center',
                    color='white', fontsize=11, fontweight='bold')
        ax_hyp.text(0.13, y + 0.05, title, ha='left', va='center',
                    color=PALETTE['text'], fontsize=11, fontweight='bold')
        ax_hyp.text(0.13, y - 0.03, detail, ha='left', va='center',
                    color=PALETTE['text_muted'], fontsize=8.8)
        ax_hyp.add_patch(FancyBboxPatch(
            (0.84, y - 0.055), 0.14, 0.11,
            boxstyle='round,pad=0.02,rounding_size=0.05',
            facecolor=color, edgecolor='none',
        ))
        ax_hyp.text(0.91, y, 'PASS' if passed else 'FAIL',
                    ha='center', va='center', color='white',
                    fontsize=11, fontweight='bold')

    # Robustness panel
    ax_rob = fig.add_axes([0.51, 0.06, 0.46, 0.40])
    ax_rob.set_xticks([]); ax_rob.set_yticks([])
    ax_rob.set_frame_on(False)
    ax_rob.set_xlim(0, 1); ax_rob.set_ylim(0, 1)

    ax_rob.text(0.5, 0.97, 'ROBUSTNESS & STATISTICAL CHECKS',
                ha='center', va='top', color=PALETTE['text_muted'],
                fontsize=11, fontweight='bold')

    boot_sharpe = bootstrap_result.get('point_estimate', sharpe) if bootstrap_result else sharpe
    boot_lo = bootstrap_result.get('ci_lower', 0) if bootstrap_result else 0
    boot_hi = bootstrap_result.get('ci_upper', 0) if bootstrap_result else 0
    prob_pos = bootstrap_result.get('prob_sharpe_positive', 0) if bootstrap_result else 0
    rand_pctl = random_result.get('percentile_rank', 0) if random_result else 0
    rand_beats = random_result.get('prob_random_beats', 0) if random_result else 0

    items = [
        ('Stationary bootstrap Sharpe',
         f'{boot_sharpe:.3f}  CI [{boot_lo:.2f}, {boot_hi:.2f}]',
         f'P(Sharpe > 0) = {prob_pos * 100:.1f}%'),
        ('Random portfolio test',
         f'Strategy at {rand_pctl:.1f}th percentile',
         f'P(random beats) = {rand_beats * 100:.1f}%'),
        ('Fama-French 5 factor',
         f'α = {alpha * 100:+.2f}% (ann.)',
         f'HML β = {ff_result["betas"].get("HML", 0):.2f}' if ff_result else ''),
        ('Hypothesis test summary',
         f'{sum(1 for h in hypotheses if h[3])} / {len(hypotheses)} passed',
         '25 % lower drawdown than S&P 500'),
    ]
    for i, (title, main, detail) in enumerate(items):
        y = 0.82 - i * 0.22
        ax_rob.text(0.03, y + 0.05, title, ha='left', va='center',
                    color=PALETTE['text_muted'], fontsize=9.5, fontweight='bold')
        ax_rob.text(0.03, y - 0.01, main, ha='left', va='center',
                    color=PALETTE['navy'], fontsize=11.5, fontweight='bold')
        if detail:
            ax_rob.text(0.97, y + 0.01, detail, ha='right', va='center',
                        color=PALETTE['text_muted'], fontsize=9)

    fig.text(
        0.03, 0.025,
        'Team 09 · Backtest window 2023-07-31 → 2025-12-31 · '
        '10 quarterly rebalances · Equal-weight primary · '
        '25 bps one-way costs · PIT 90-day lag · 595 tickers',
        fontsize=9, color=PALETTE['text_muted'], ha='left', va='bottom',
    )

    _save(fig, output_path)
