"""arq worker that runs a Kubecost scan end-to-end.

Pipeline (each phase ends with a commit so frontend polling sees progress):

    1. status=RUNNING, started_at, progress="Connecting to Kubecost"
    2. concurrent: get_allocation, get_allocation(prior_window), get_assets, get_savings
    3. progress="Building digest"  → preprocessor.build_digest
    4. progress="Retrieving knowledge"  → RagService.retrieve per category
    5. progress="Analyzing (model: <name>)"  → OllamaService.analyze
    6. status=COMPLETED, completed_at, total_cost_usd, raw_data, digest
       OR status=FAILED, error_message

The worker never re-raises. arq's default retry would re-run a failed scan;
we want failed scans to stay failed (the user retries with a new scan, which
is a single click in the UI).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar

import structlog
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import AsyncSessionLocal
from app.models.environment import Environment
from app.models.report import Report
from app.models.scan import Scan, ScanStatus
from app.services.crypto import decrypt
from app.services.finding_enricher import enrich_findings
from app.services.kubecost import KubecostClient, KubecostError
from app.services.ollama_client import OllamaError, OllamaService
from app.services.preprocessor import build_digest, prior_window
from app.services.rag import RagService

# -- Constants ---------------------------------------------------------------

RAW_DATA_MAX_BYTES = 256 * 1024
MAX_RAG_RESULTS = 6
RAG_RESULTS_PER_QUERY = 2

# Category → query string. A category with no findings contributes no query
# (saves embedding compute and keeps RAG context tightly focused).
RAG_QUERIES: dict[str, str] = {
    "idle_workloads": "idle workloads kubernetes how to identify and remediate",
    "over_provisioned": "kubernetes resource requests rightsizing best practices",
    "pvc_waste": "EBS persistent volume waste oversized unmounted",
    "anomalies": "cost anomaly investigation kubernetes namespace",
    "savings_signals": "EKS spot instances savings plans node groups",
}

# Windows for which we can compute a prior comparison via prior_window().
# `lastmonth` is itself backward-looking so no comparison is meaningful.
_PRIOR_COMPARABLE_WINDOWS = frozenset({"7d", "30d", "24h", "today", "month"})


# -- Dependencies ------------------------------------------------------------


SessionContextFactory = Callable[[], "AsyncIterator[AsyncSession]"]
KubecostFactory = Callable[[Environment], KubecostClient]


@dataclass
class WorkerDeps:
    session_factory: SessionContextFactory
    kubecost_factory: KubecostFactory
    rag_service: RagService
    ollama_service: OllamaService

    @classmethod
    def default(cls) -> WorkerDeps:
        return cls(
            session_factory=_default_session_factory,
            kubecost_factory=_default_kubecost_factory,
            rag_service=RagService(),
            ollama_service=OllamaService(),
        )


@asynccontextmanager
async def _default_session_factory() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


def _default_kubecost_factory(env: Environment) -> KubecostClient:
    token = decrypt(env.auth_token_encrypted) if env.auth_token_encrypted else None
    return KubecostClient(base_url=env.kubecost_url, auth_token=token)


# -- Helpers -----------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


async def _commit_phase(
    session: AsyncSession,
    scan: Scan,
    *,
    status: ScanStatus | None = None,
    progress: str | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    error_message: str | None = None,
    total_cost_usd: float | None = None,
    raw_data: dict[str, Any] | None = None,
    digest: dict[str, Any] | None = None,
) -> None:
    if status is not None:
        scan.status = status
    if progress is not None:
        scan.progress_message = progress
    if started_at is not None:
        scan.started_at = started_at
    if completed_at is not None:
        scan.completed_at = completed_at
    if error_message is not None:
        scan.error_message = error_message
    if total_cost_usd is not None:
        scan.total_cost_usd = total_cost_usd
    if raw_data is not None:
        scan.raw_data = raw_data
    if digest is not None:
        scan.digest = digest
    await session.commit()


def _maybe_truncate_raw_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    serialized = json.dumps(raw_data, separators=(",", ":")).encode("utf-8")
    if len(serialized) > RAW_DATA_MAX_BYTES:
        return {"truncated": True, "original_bytes": len(serialized)}
    return raw_data


def _build_rag_queries(digest: dict[str, Any]) -> list[str]:
    return [query for category, query in RAG_QUERIES.items() if digest.get(category)]


async def _retrieve_rag_context(rag: RagService, queries: list[str]) -> list[str]:
    if not queries:
        return []
    results_per_query = await asyncio.gather(
        *(rag.retrieve(q, k=RAG_RESULTS_PER_QUERY) for q in queries)
    )
    seen: set[str] = set()
    out: list[str] = []
    for results in results_per_query:
        for r in results:
            if r in seen:
                continue
            seen.add(r)
            out.append(r)
            if len(out) >= MAX_RAG_RESULTS:
                return out
    return out


async def _fetch_kubecost_concurrently(
    client: KubecostClient,
    window: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any | None]]:
    if window in _PRIOR_COMPARABLE_WINDOWS:
        prior_iso = prior_window(window)
        allocation, prior_allocation, assets, savings = await asyncio.gather(
            client.get_allocation(window=window),
            client.get_allocation(window=prior_iso),
            client.get_assets(window=window),
            client.get_savings(window=window),
        )
    else:
        allocation, assets, savings = await asyncio.gather(
            client.get_allocation(window=window),
            client.get_assets(window=window),
            client.get_savings(window=window),
        )
        prior_allocation = {"data": []}
    return allocation, prior_allocation, assets, savings


# -- Pipeline ----------------------------------------------------------------


async def _run_pipeline(
    session: AsyncSession,
    scan: Scan,
    env: Environment,
    deps: WorkerDeps,
    log: Any,
) -> None:
    # Phase 1 — mark running.
    await _commit_phase(
        session,
        scan,
        status=ScanStatus.RUNNING,
        started_at=_now(),
        progress="Connecting to Kubecost",
    )
    log.info("scan_started")

    # Phase 2 — pull from Kubecost concurrently.
    client = deps.kubecost_factory(env)
    allocation, prior_allocation, assets, savings = await _fetch_kubecost_concurrently(
        client, scan.window
    )
    log.info("kubecost_data_fetched", window=scan.window)

    # Phase 3 — preprocessor.
    await _commit_phase(session, scan, progress="Building digest")
    digest = build_digest(allocation, prior_allocation, assets, savings, scan.window)
    log.info(
        "digest_built",
        total_cost_usd=digest.get("total_cost_usd"),
        truncated=digest.get("truncated"),
    )

    # Phase 4 — RAG retrieval.
    await _commit_phase(session, scan, progress="Retrieving knowledge")
    rag_queries = _build_rag_queries(digest)
    rag_context = await _retrieve_rag_context(deps.rag_service, rag_queries)
    log.info("rag_retrieved", queries=len(rag_queries), snippets=len(rag_context))

    # Phase 5 — Ollama analysis.
    model_name = deps.ollama_service.model
    await _commit_phase(session, scan, progress=f"Analyzing (model: {model_name})")
    log = log.bind(model=model_name)
    result = await deps.ollama_service.analyze(digest, rag_context)
    log.info(
        "ollama_analyzed",
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        duration_ms=result.duration_ms,
    )
    if result.consistency_violations:
        # The report contradicts the digest even after one repair round. We
        # still persist it (a flawed report is more useful than none) but
        # log loudly so operators can investigate and tune the prompt.
        log.warning(
            "ollama_report_inconsistent_after_repair",
            violations=result.consistency_violations,
        )

    # Phase 6 — persist Report and complete the scan.
    raw_data = {
        "allocation": allocation,
        "prior_allocation": prior_allocation,
        "assets": assets,
        "savings": savings,
    }
    # Backfill structured Finding fields from the digest based on each
    # finding's ``digest_reference``. The model's job is judgment; mechanical
    # field copying is the worker's job. The validator already ran against
    # the un-enriched report (so it can catch "no idle workloads" lies
    # before they're masked); the enriched findings are what we persist.
    enriched_findings = enrich_findings(result.report.findings, digest)
    report = Report(
        scan_id=scan.id,
        executive_summary=result.report.executive_summary,
        findings=[f.model_dump() for f in enriched_findings],
        estimated_monthly_savings_usd=result.report.estimated_monthly_savings_usd,
        model_used=model_name,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        duration_ms=result.duration_ms,
    )
    session.add(report)
    await _commit_phase(
        session,
        scan,
        status=ScanStatus.COMPLETED,
        completed_at=_now(),
        progress="Completed",
        total_cost_usd=digest.get("total_cost_usd"),
        raw_data=_maybe_truncate_raw_data(raw_data),
        digest=digest,
    )
    log.info("scan_completed")


async def _mark_failed(session: AsyncSession, scan: Scan, error: str) -> None:
    await _commit_phase(
        session,
        scan,
        status=ScanStatus.FAILED,
        completed_at=_now(),
        progress="Failed",
        error_message=error,
    )


# -- Entry point -------------------------------------------------------------


async def run_scan(ctx: dict[str, Any], scan_id: int) -> None:
    """arq worker function. Never re-raises — failed scans stay failed."""
    deps: WorkerDeps = ctx.get("deps") or WorkerDeps.default()
    log = structlog.get_logger().bind(scan_id=scan_id)

    async with deps.session_factory() as session:
        scan = await session.get(Scan, scan_id)
        if scan is None:
            log.warning("scan_missing")
            return
        env = await session.get(Environment, scan.environment_id)
        if env is None:
            log.error("environment_missing", environment_id=scan.environment_id)
            await _mark_failed(session, scan, "Environment row not found")
            return
        log = log.bind(environment_id=env.id)

        try:
            await _run_pipeline(session, scan, env, deps, log)
        except KubecostError as exc:
            log.warning("scan_failed_kubecost", error=str(exc))
            await _mark_failed(session, scan, f"Kubecost: {exc}")
        except OllamaError as exc:
            log.warning("scan_failed_ollama", error=str(exc))
            await _mark_failed(session, scan, f"Ollama: {exc}")
        except Exception as exc:
            log.exception("scan_unexpected_error")
            await _mark_failed(session, scan, f"Unexpected: {exc!r}")


# -- arq WorkerSettings ------------------------------------------------------


async def _on_startup(ctx: dict[str, Any]) -> None:
    ctx["deps"] = WorkerDeps.default()


class WorkerSettings:
    """arq looks for this class via ``app.workers.scan_worker.WorkerSettings``."""

    functions: ClassVar[list[Any]] = [run_scan]
    on_startup = staticmethod(_on_startup)
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 1  # one scan at a time keeps Ollama from thrashing
    job_timeout = 600
