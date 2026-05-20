"""Pydantic schemas for Report."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

Severity = Literal["critical", "high", "medium", "low", "info"]
Category = Literal[
    "idle_workloads",
    "over_provisioning",
    "pvc_waste",
    "anomaly",
    "rightsizing",
    "spot_opportunity",
    "reserved_instance",
    "cluster_efficiency",
    "other",
]


class Finding(BaseModel):
    title: str
    severity: Severity
    category: Category
    impact_usd: float | None = None  # Estimated monthly impact
    affected_resource: str | None = None  # e.g. "namespace/data-science"
    recommendation: str
    rationale: str | None = None  # Why this matters; references to docs
    # Pointer to the digest entry this finding is about. The LLM sets this;
    # the worker resolves it into ``impact_usd`` and ``affected_resource``
    # post-analyze. The model is unreliable at mechanical field copying but
    # reliable at choosing identities — this split keeps each side honest.
    #
    # Format: ``{category}/{entry_name}`` where ``category`` is one of
    # ``idle_workloads`` / ``over_provisioned`` / ``pvc_waste`` /
    # ``anomalies`` and ``entry_name`` is the entry's ``name`` field (or
    # ``namespace`` for anomalies). ``null`` for cluster-wide findings.
    digest_reference: str | None = None


class ReportContent(BaseModel):
    """LLM-produced portion of a Report.

    The DB-side fields (id, scan_id, model_used, created_at, token metrics)
    are filled in by the worker — the model never produces them.
    """

    executive_summary: str
    findings: list[Finding]
    estimated_monthly_savings_usd: float | None = None


class ReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scan_id: int
    executive_summary: str
    findings: list[Finding]
    estimated_monthly_savings_usd: float | None
    model_used: str
    # Observability fields persisted by the scan worker (B5). Optional
    # because older Report rows may have None — pre-B5 fixtures or repaired
    # rows. ``from_attributes=True`` picks them up directly from the ORM.
    duration_ms: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    created_at: datetime
