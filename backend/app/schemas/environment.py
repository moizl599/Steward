"""Pydantic schemas for Environment."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.schemas.scan import LatestScanSummary


class EnvironmentBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kubecost_url: HttpUrl
    aws_region: str = Field(min_length=1, max_length=64)
    cluster_name: str | None = Field(default=None, max_length=255)


class EnvironmentCreate(EnvironmentBase):
    auth_token: str | None = None


class EnvironmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    kubecost_url: HttpUrl | None = None
    auth_token: str | None = None
    aws_region: str | None = Field(default=None, min_length=1, max_length=64)
    cluster_name: str | None = Field(default=None, max_length=255)


class EnvironmentRead(EnvironmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    last_connection_check: datetime | None
    last_connection_ok: bool
    last_connection_error: str | None
    created_at: datetime
    updated_at: datetime
    # Most-recent scan for this environment (any status). Populated by the
    # API; never set on the SQLAlchemy model directly.
    latest_scan: LatestScanSummary | None = None


class ConnectionTestResult(BaseModel):
    ok: bool
    message: str
    kubecost_version: str | None = None
    latency_ms: int | None = None
