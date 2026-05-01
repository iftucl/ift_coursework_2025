"""Shared utility: render a data table as a styled PNG using matplotlib.

Usage in any pipeline script:
    from _table_utils import save_table_png

    save_table_png(
        headers=["Col A", "Col B"],
        rows=[["val1", "val2"], ...],
        title="My Table",
        filepath=CHARTS / "my_table.png",
    )
"""

from pathlib import Path

import matplotlib.pyplot as plt

HEADER_COLOR = "#2166ac"  # blue
HEADER_TEXT = "white"
ALT_ROW_COLOR = "#eef2f7"  # light blue-grey
HIGH_COLOR = "#fff3cd"  # amber highlight for key rows
BORDER_COLOR = "#cccccc"


def save_table_png(
    headers: list,
    rows: list,
    title: str,
    filepath: Path,
    col_widths: list = None,
    highlight_rows: list = None,  # 0-based row indices to highlight amber
    bold_rows: list = None,  # 0-based row indices to bold
    footnote: str = None,
    figsize: tuple = None,
    fontsize: int = 10,
):
    """Render a table as a clean PNG file.

    Parameters
    ----------
    headers      : list of column header strings
    rows         : list of lists — each inner list is one data row
    title        : chart title (shown above table)
    filepath     : Path object for output PNG
    col_widths   : relative column widths (sum doesn't need to equal 1);
                   defaults to equal widths
    highlight_rows : row indices (0-based in `rows`) to shade amber
    bold_rows      : row indices (0-based in `rows`) to bold
    footnote     : optional small text below the table
    figsize      : (width, height) in inches; auto-computed if None
    fontsize     : table font size (default 10)
    """
    n_rows = len(rows)
    n_cols = len(headers)

    highlight_rows = set(highlight_rows or [])
    bold_rows = set(bold_rows or [])

    # Auto figure size: wider for more columns, taller for more rows
    if figsize is None:
        w = max(8, n_cols * 1.6)
        h = max(2.5, n_rows * 0.38 + 1.8 + (0.3 if footnote else 0))
        figsize = (w, h)

    fig, ax = plt.subplots(figsize=figsize)
    ax.axis("off")

    # ── Build table ───────────────────────────────────────────────────────────
    if col_widths is None:
        col_widths = [1.0 / n_cols] * n_cols
    else:
        total = sum(col_widths)
        col_widths = [w / total for w in col_widths]

    tbl = ax.table(
        cellText=rows,
        colLabels=headers,
        loc="center",
        cellLoc="center",
        colWidths=col_widths,
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(fontsize)
    tbl.scale(1, 1.6)

    # ── Style header row ──────────────────────────────────────────────────────
    for j in range(n_cols):
        cell = tbl[0, j]
        cell.set_facecolor(HEADER_COLOR)
        cell.set_text_props(color=HEADER_TEXT, fontweight="bold")
        cell.set_edgecolor(HEADER_COLOR)

    # ── Style data rows ───────────────────────────────────────────────────────
    for i, row in enumerate(rows):
        tbl_row = i + 1  # +1 because row 0 is header
        for j in range(n_cols):
            cell = tbl[tbl_row, j]
            cell.set_edgecolor(BORDER_COLOR)

            if i in highlight_rows:
                cell.set_facecolor(HIGH_COLOR)
            elif i % 2 == 1:
                cell.set_facecolor(ALT_ROW_COLOR)
            else:
                cell.set_facecolor("white")

            if i in bold_rows:
                cell.set_text_props(fontweight="bold")

    # ── Title ─────────────────────────────────────────────────────────────────
    ax.set_title(title, fontsize=12, fontweight="bold", pad=14, loc="center", color="#222222")

    # ── Footnote ─────────────────────────────────────────────────────────────
    if footnote:
        fig.text(
            0.5,
            0.01,
            footnote,
            ha="center",
            va="bottom",
            fontsize=8,
            color="#555555",
            style="italic",
        )

    fig.tight_layout(pad=0.5)
    fig.savefig(filepath, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved {Path(filepath).name}")
