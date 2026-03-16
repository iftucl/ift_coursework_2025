#!/usr/bin/env python3
"""
Pipeline execution results and status tracking.

Provides structured representations of pipeline run data to eliminate
hard-coded summary numbers and enable proper status reporting.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional


class ExportStatus(Enum):
    """Export status enumeration."""

    LOCAL_ONLY = "local_only"  # Only local file export succeeded
    MINIO_SUCCESS = "minio_success"  # Both local and MinIO succeeded
    MINIO_FAILED = "minio_failed"  # Local succeeded, MinIO failed
    DISABLED = "disabled"  # MinIO not configured (intentional)
    UNKNOWN = "unknown"  # Never attempted


@dataclass
class StepResult:
    """Result metadata from a single pipeline step."""

    step_number: int
    name: str
    success: bool
    row_count: int = 0
    files_created: int = 0
    duration_seconds: float = 0.0
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        status = "✅ PASS" if self.success else "❌ FAIL"
        return f"{status} - Step {self.step_number}/4: {self.name} ({self.row_count} rows, {self.files_created} files)"


@dataclass
class PipelineRunSummary:
    """Complete summary of a pipeline execution run."""

    start_time: datetime
    end_time: Optional[datetime] = None

    # Step results
    step_results: Dict[int, StepResult] = field(default_factory=dict)

    # Actual counts from current run (read from output files)
    step1_factor_count: int = 0  # Factors created in Step 1
    step2_portfolio_count: int = 0  # Portfolio stocks selected in Step 2
    step2_selections_count: int = 0  # Selections ranked in Step 2
    step3_signal_count: int = 0  # Signals generated in Step 3
    step3_buy_count: int = 0  # BUY signals
    step3_sell_count: int = 0  # SELL signals
    step3_hold_count: int = 0  # HOLD signals

    # Export status
    export_status: ExportStatus = ExportStatus.UNKNOWN
    minio_config_provided: bool = False
    minio_available: bool = False
    minio_bucket: Optional[str] = None
    minio_endpoint: Optional[str] = None
    minio_connection_error: Optional[str] = None
    minio_upload_errors: int = 0

    # local files
    local_files_created: int = 0
    local_path: Optional[Path] = None

    @property
    def duration_seconds(self) -> float:
        """Total execution time in seconds."""
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0

    @property
    def all_steps_passed(self) -> bool:
        """Whether all completed steps passed."""
        if not self.step_results:
            return False
        return all(result.success for result in self.step_results.values())

    @property
    def steps_completed(self) -> int:
        """Number of steps completed."""
        return len(self.step_results)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "duration_seconds": self.duration_seconds,
            "steps_passed": self.all_steps_passed,
            "steps_completed": self.steps_completed,
            "step_results": {
                k: {
                    "name": v.name,
                    "success": v.success,
                    "rows": v.row_count,
                    "files": v.files_created,
                    "duration": v.duration_seconds,
                }
                for k, v in self.step_results.items()
            },
            "counts": {
                "factors": self.step1_factor_count,
                "portfolio": self.step2_portfolio_count,
                "selections": self.step2_selections_count,
                "signals": self.step3_signal_count,
                "buy_signals": self.step3_buy_count,
                "sell_signals": self.step3_sell_count,
                "hold_signals": self.step3_hold_count,
            },
            "export": {
                "status": self.export_status.value,
                "minio_configured": self.minio_config_provided,
                "minio_available": self.minio_available,
                "minio_bucket": self.minio_bucket,
                "minio_endpoint": self.minio_endpoint,
                "minio_connection_error": self.minio_connection_error,
                "local_files": self.local_files_created,
            },
        }
