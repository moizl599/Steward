"""Report model — the LLM-produced analysis for a Scan."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id"), unique=True)

    # Headline narrative (LLM output)
    executive_summary: Mapped[str] = mapped_column(Text)

    # Structured findings: [{title, severity, category, impact_usd, recommendation, ...}]
    findings: Mapped[list] = mapped_column(JSON, default=list)

    # Estimated total monthly savings if all recommendations applied
    estimated_monthly_savings_usd: Mapped[float | None] = mapped_column(nullable=True)

    # Which model produced this report (for debugging/comparison)
    model_used: Mapped[str] = mapped_column(String(128))

    # Token usage / latency for observability
    prompt_tokens: Mapped[int | None] = mapped_column(nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    scan = relationship("Scan", back_populates="report")
