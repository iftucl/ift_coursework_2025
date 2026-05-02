from __future__ import annotations

"""ORM models for core project tables."""

from datetime import date, datetime
from typing import Generic, Optional, TypeVar

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)

try:
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

    class Base(DeclarativeBase):
        """Shared SQLAlchemy declarative base for project models."""

except ImportError:
    from sqlalchemy.orm import declarative_base

    T = TypeVar("T")

    class Mapped(Generic[T]):
        """Typing shim for SQLAlchemy 1.4 runtime environments."""

    def mapped_column(*args, **kwargs):
        return Column(*args, **kwargs)

    Base = declarative_base()


class FactorObservation(Base):
    __tablename__ = "factor_observations"
    __table_args__ = (
        UniqueConstraint("symbol", "observation_date", "factor_name", name="uniq_observation"),
        CheckConstraint(
            "metric_frequency IN ('daily','weekly','monthly','quarterly','annual','unknown')",
            name="ck_factor_observations_metric_frequency",
        ),
        Index("idx_factor_obs_symbol", "symbol"),
        Index("idx_factor_obs_observation_date", "observation_date"),
        Index("idx_factor_obs_symbol_factor_date", "symbol", "factor_name", "observation_date"),
        Index("idx_factor_obs_factor_date", "factor_name", "observation_date"),
        Index("idx_factor_obs_publish_date", "publish_date"),
        Index("idx_factor_obs_symbol_publish_date", "symbol", "publish_date"),
        {"schema": "systematic_equity"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    factor_name: Mapped[str] = mapped_column(String(50), nullable=False)
    factor_value: Mapped[Optional[float]] = mapped_column(Numeric(18, 6))
    source: Mapped[Optional[str]] = mapped_column(String(50))
    metric_frequency: Mapped[Optional[str]] = mapped_column(String(20))
    source_report_date: Mapped[Optional[date]] = mapped_column(Date)
    publish_date: Mapped[Optional[date]] = mapped_column(Date)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class FinancialObservation(Base):
    __tablename__ = "financial_observations"
    __table_args__ = (
        UniqueConstraint("symbol", "report_date", "metric_name", name="uniq_financial_observation"),
        CheckConstraint(
            "period_type IN ('annual','quarterly','ttm','snapshot','unknown')",
            name="ck_financial_observations_period_type",
        ),
        CheckConstraint(
            "metric_definition IN ('provider_reported','normalized','estimated','unknown')",
            name="ck_financial_observations_metric_definition",
        ),
        Index("idx_financial_obs_symbol", "symbol"),
        Index("idx_financial_obs_report_date", "report_date"),
        Index("idx_financial_obs_publish_date", "publish_date"),
        Index("idx_financial_obs_symbol_publish_date", "symbol", "publish_date"),
        {"schema": "systematic_equity"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_value: Mapped[Optional[float]] = mapped_column(Numeric(24, 6))
    currency: Mapped[Optional[str]] = mapped_column(String(16))
    period_type: Mapped[Optional[str]] = mapped_column(String(20))
    metric_definition: Mapped[Optional[str]] = mapped_column(String(50))
    source: Mapped[Optional[str]] = mapped_column(String(50))
    value_source: Mapped[Optional[str]] = mapped_column(String(64))
    as_of: Mapped[Optional[date]] = mapped_column(Date)
    publish_date: Mapped[Optional[date]] = mapped_column(Date)
    publish_date_source: Mapped[Optional[str]] = mapped_column(String(64))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'success', 'failed')", name="ck_pipeline_runs_status"
        ),
        Index("idx_pipeline_runs_run_date", "run_date"),
        Index("idx_pipeline_runs_status", "status"),
        {"schema": "systematic_equity"},
    )

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    frequency: Mapped[Optional[str]] = mapped_column(String(20))
    backfill_years: Mapped[Optional[int]] = mapped_column(Integer)
    company_limit: Mapped[Optional[int]] = mapped_column(Integer)
    enabled_extractors: Mapped[Optional[str]] = mapped_column(Text)
    rows_written: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    error_traceback: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
