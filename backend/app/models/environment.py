"""Environment model — represents one Kubecost connection (typically one EKS cluster)."""

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Environment(Base):
    __tablename__ = "environments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    kubecost_url: Mapped[str] = mapped_column(String(512))
    # Encrypted at rest. See app.services.crypto.
    auth_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    aws_region: Mapped[str] = mapped_column(String(64))
    cluster_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    last_connection_check: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_connection_ok: Mapped[bool] = mapped_column(default=False)
    last_connection_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
