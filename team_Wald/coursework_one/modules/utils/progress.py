"""
UCL -- Institute of Finance & Technology
Author  : Team 09
Topic   : Rich animated progress display for the pipeline
Project : CW1 - Value + News Sentiment Strategy

Provides a PipelineProgressManager that wraps Rich's Live display
to show animated progress bars, spinners, live stats counters, and
a final colourful summary table.
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

console = Console()

STATUS_STYLES = {
    "success": "green",
    "empty": "yellow",
    "error": "red",
    "info": "cyan",
    "skip": "dim",
}


@dataclass
class StageRecord:
    """Tracks metrics for a single pipeline stage."""

    name: str
    total: int = 0
    completed: int = 0
    success: int = 0
    empty: int = 0
    errors: int = 0
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None

    @property
    def elapsed(self) -> float:
        end = self.end_time or time.time()
        return end - self.start_time

    @property
    def elapsed_str(self) -> str:
        e = self.elapsed
        if e < 60:
            return f"{e:.1f}s"
        return f"{e / 60:.1f}m"


class PipelineProgressManager:
    """Animated Rich progress display for the full pipeline.

    Usage::

        pm = PipelineProgressManager()
        pm.start()
        pm.begin_stage("Yahoo Finance Extraction", total=678)
        for ticker in tickers:
            ...
            pm.advance(f"{ticker}: 250 rows", "success")
        pm.complete_stage()
        pm.stop()
        pm.print_summary()
    """

    def __init__(self):
        self._progress = Progress(
            SpinnerColumn("dots"),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=40, complete_style="green", finished_style="bold green"),
            MofNCompleteColumn(),
            TextColumn("[dim]{task.fields[status_text]}"),
            TimeElapsedColumn(),
            console=console,
            expand=False,
        )
        self._live: Live | None = None
        self._current_task_id = None
        self._stages: list[StageRecord] = []
        self._current_stage: StageRecord | None = None
        self._stats: dict[str, str] = {}
        self._pipeline_start: float = 0.0

    def start(self):
        """Begin the live display."""
        if self._pipeline_start == 0.0:
            self._pipeline_start = time.time()
        self._live = Live(self._build_layout(), console=console, refresh_per_second=10, transient=False)
        self._live.start()

    def stop(self):
        """Stop the live display."""
        if self._current_stage and self._current_stage.end_time is None:
            self._current_stage.end_time = time.time()
        if self._live:
            self._live.stop()
            self._live = None

    def begin_stage(self, name: str, total: int = 0):
        """Start a new pipeline stage with a progress bar."""
        # Complete previous stage
        if self._current_stage and self._current_stage.end_time is None:
            self._current_stage.end_time = time.time()

        stage = StageRecord(name=name, total=total)
        self._stages.append(stage)
        self._current_stage = stage

        self._current_task_id = self._progress.add_task(
            f"[bold]{name}",
            total=total if total > 0 else None,
            status_text="starting...",
        )
        self._refresh()

    def advance(self, description: str = "", status: str = "success"):
        """Advance the current stage bar by 1 item."""
        if self._current_task_id is None or self._current_stage is None:
            return

        self._current_stage.completed += 1
        if status == "success":
            self._current_stage.success += 1
        elif status == "empty":
            self._current_stage.empty += 1
        elif status == "error":
            self._current_stage.errors += 1

        colour = STATUS_STYLES.get(status, "white")
        status_text = f"[{colour}]{description}[/{colour}]" if description else ""

        self._progress.update(self._current_task_id, advance=1, status_text=status_text)
        self._refresh()

    def complete_stage(self, summary: str = ""):
        """Mark the current stage as complete."""
        if self._current_stage:
            self._current_stage.end_time = time.time()
        if self._current_task_id is not None:
            stage = self._current_stage
            if stage:
                status = (
                    f"[green]done[/green] — "
                    f"{stage.success} ok, {stage.empty} empty, {stage.errors} err "
                    f"({stage.elapsed_str})"
                )
            else:
                status = f"[green]done[/green] {summary}"
            self._progress.update(self._current_task_id, status_text=status)
            # Ensure bar is filled
            if self._current_stage and self._current_stage.total > 0:
                remaining = self._current_stage.total - self._current_stage.completed
                if remaining > 0:
                    self._progress.update(self._current_task_id, advance=remaining)
        self._refresh()

    def update_stats(self, key: str, value):
        """Update a live stats counter shown in the side panel."""
        self._stats[key] = str(value)
        self._refresh()

    def log(self, message: str, style: str = ""):
        """Print a log line below the live display."""
        if self._live:
            self._live.console.print(f"  {message}", style=style, highlight=False)
        else:
            console.print(f"  {message}", style=style, highlight=False)

    @contextmanager
    def spinner(self, message: str):
        """Context manager that shows a spinner for a brief operation."""
        task_id = self._progress.add_task(f"[bold]{message}", total=None, status_text="")
        self._refresh()
        try:
            yield
        finally:
            self._progress.update(task_id, status_text="[green]done[/green]")
            self._progress.stop_task(task_id)
            self._refresh()

    def print_banner(self, title: str, subtitle: str = ""):
        """Print a Rich panel banner."""
        text = Text(title, style="bold white")
        if subtitle:
            text.append(f"\n{subtitle}", style="dim")
        console.print(Panel(text, border_style="blue", padding=(0, 2)))

    def print_summary(self):
        """Print a final Rich summary table of all stages."""
        elapsed = time.time() - self._pipeline_start

        table = Table(
            title="[bold]Pipeline Execution Summary[/bold]",
            show_header=True,
            header_style="bold cyan",
            border_style="blue",
            padding=(0, 1),
        )
        table.add_column("#", style="dim", width=3, justify="right")
        table.add_column("Stage", min_width=30)
        table.add_column("Items", justify="right", width=8)
        table.add_column("Success", justify="right", style="green", width=8)
        table.add_column("Empty", justify="right", style="yellow", width=8)
        table.add_column("Errors", justify="right", style="red", width=8)
        table.add_column("Time", justify="right", width=8)

        for i, stage in enumerate(self._stages, 1):
            err_style = "bold red" if stage.errors > 0 else "red"
            table.add_row(
                str(i),
                stage.name,
                str(stage.completed),
                str(stage.success),
                str(stage.empty),
                Text(str(stage.errors), style=err_style),
                stage.elapsed_str,
            )

        # Totals row
        total_items = sum(s.completed for s in self._stages)
        total_ok = sum(s.success for s in self._stages)
        total_empty = sum(s.empty for s in self._stages)
        total_err = sum(s.errors for s in self._stages)
        table.add_section()
        table.add_row(
            "",
            "[bold]TOTAL[/bold]",
            f"[bold]{total_items}[/bold]",
            f"[bold green]{total_ok}[/bold green]",
            f"[bold yellow]{total_empty}[/bold yellow]",
            Text(str(total_err), style="bold red"),
            f"[bold]{elapsed:.1f}s[/bold]" if elapsed < 60 else f"[bold]{elapsed / 60:.1f}m[/bold]",
        )

        console.print()
        console.print(table)
        console.print()

    def print_results_table(self, title: str, headers: list[str], rows: list[list], styles: list[str] | None = None):
        """Print a Rich-formatted results table (for value/sentiment/composite scores)."""
        table = Table(title=f"[bold]{title}[/bold]", show_header=True, header_style="bold cyan", border_style="blue")
        if styles is None:
            styles = [""] * len(headers)
        for header, style in zip(headers, styles):
            table.add_column(header, style=style)
        for row in rows:
            table.add_row(*[str(v) for v in row])
        console.print(table)

    # -- parallel stage helpers -------------------------------------------

    def begin_parallel_stages(self, stages: dict[str, int]):
        """Start multiple concurrent progress bars that run simultaneously.

        Unlike ``begin_stage`` (which auto-closes the previous stage),
        this creates N progress bars at once so independent stages can
        advance in parallel.

        :param stages: Ordered dict mapping stage name to total items
        """
        # Close any existing sequential stage
        if self._current_stage and self._current_stage.end_time is None:
            self._current_stage.end_time = time.time()
        self._current_stage = None
        self._current_task_id = None

        self._parallel_tasks: dict[str, int] = {}
        self._parallel_stages: dict[str, StageRecord] = {}

        for name, total in stages.items():
            stage = StageRecord(name=name, total=total)
            self._stages.append(stage)
            self._parallel_stages[name] = stage
            task_id = self._progress.add_task(
                f"[bold]{name}",
                total=total if total > 0 else None,
                status_text="starting...",
            )
            self._parallel_tasks[name] = task_id
        self._refresh()

    def advance_parallel(self, stage_name: str, description: str = "", status: str = "success"):
        """Advance one of the concurrent parallel progress bars by 1."""
        task_id = self._parallel_tasks.get(stage_name)
        stage = self._parallel_stages.get(stage_name)
        if task_id is None or stage is None:
            return

        stage.completed += 1
        if status == "success":
            stage.success += 1
        elif status == "empty":
            stage.empty += 1
        elif status == "error":
            stage.errors += 1

        colour = STATUS_STYLES.get(status, "white")
        status_text = f"[{colour}]{description}[/{colour}]" if description else ""
        self._progress.update(task_id, advance=1, status_text=status_text)
        self._refresh()

    def complete_parallel_stages(self):
        """Mark all parallel stages as complete and show their summaries."""
        for name, stage in self._parallel_stages.items():
            stage.end_time = time.time()
            task_id = self._parallel_tasks[name]
            status = (
                f"[green]done[/green] — "
                f"{stage.success} ok, {stage.empty} empty, {stage.errors} err "
                f"({stage.elapsed_str})"
            )
            self._progress.update(task_id, status_text=status)
            remaining = stage.total - stage.completed
            if remaining > 0:
                self._progress.update(task_id, advance=remaining)
        self._parallel_tasks = {}
        self._parallel_stages = {}
        self._refresh()

    # -- internal helpers -------------------------------------------------

    def _build_layout(self):
        """Build the Rich layout with progress bars and stats panel."""
        layout = Layout()
        stats_text = "\n".join(f"  [cyan]{k}:[/cyan] {v}" for k, v in self._stats.items())
        stats_panel = Panel(stats_text or "  Initialising...", title="Live Stats", border_style="dim")
        layout.split_row(
            Layout(self._progress, name="progress", ratio=3),
            Layout(stats_panel, name="stats", ratio=1),
        )
        return layout

    def _refresh(self):
        """Refresh the live display."""
        if self._live:
            self._live.update(self._build_layout())
