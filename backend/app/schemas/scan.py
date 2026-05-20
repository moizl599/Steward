"""Pydantic schemas for Scan."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.scan import ScanStatus


class ScanCreate(BaseModel):
    window: str = "7d"


class ScanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    status: ScanStatus
    progress_message: str | None
    error_message: str | None
    window: str
    total_cost_usd: float | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class LatestScanSummary(BaseModel):
    """Compact subset of Scan suitable for embedding in EnvironmentRead.

    Excludes the heavy ``raw_data``/``digest`` columns so the dashboard list
    response stays small. ``finding_count`` is sourced from the joined Report
    row when the scan has a report; ``None`` for queued/running/failed scans.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: ScanStatus
    window: str
    total_cost_usd: float | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    finding_count: int | None = None


class ScanWithEnvRead(ScanRead):
    """ScanRead enriched with env name and finding count for the reports table."""

    environment_name: str | None = None
    finding_count: int | None = None
