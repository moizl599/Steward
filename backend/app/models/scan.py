"""Scan model — one cost analysis run for an Environment."""

import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ScanStatus(str, enum.Enum):  # noqa: UP042 - keeping str+Enum for Pydantic v2 compat; revisit if migrating to StrEnum
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(primary_key=True)
    environment_id: Mapped[int] = mapped_column(ForeignKey("environments.id"))

    status: Mapped[ScanStatus] = mapped_column(Enum(ScanStatus), default=ScanStatus.QUEUED)
    progress_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Time window pulled from Kubecost (e.g. "7d", "30d")
    window: Mapped[str] = mapped_column(String(16), default="7d")

    # Raw aggregated data from Kubecost (allocation, assets, savings)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Pre-processed digest fed to the LLM
    digest: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Total cost for the window (USD), denormalized for fast list views
    total_cost_usd: Mapped[float | None] = mapped_column(nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    report = relationship("Report", back_populates="scan", uselist=False)
