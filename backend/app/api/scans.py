"""Scan trigger and retrieval endpoints."""

from datetime import datetime

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_arq_pool
from app.db import get_db
from app.models import Environment, Report, Scan, ScanStatus
from app.schemas import ReportRead, ScanCreate, ScanRead, ScanWithEnvRead

router = APIRouter(tags=["scans"])


@router.post(
    "/environments/{env_id}/scan",
    response_model=ScanRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_scan(
    env_id: int,
    payload: ScanCreate,
    db: AsyncSession = Depends(get_db),
    arq: ArqRedis = Depends(get_arq_pool),
) -> Scan:
    env = await db.get(Environment, env_id)
    if env is None:
        raise HTTPException(status_code=404, detail="Environment not found")

    scan = Scan(environment_id=env.id, window=payload.window, status=ScanStatus.QUEUED)
    db.add(scan)
    await db.commit()
    await db.refresh(scan)

    # Enqueue background work. The worker is implemented in app/workers/scan_worker.py.
    await arq.enqueue_job("run_scan", scan.id)

    return scan


@router.get("/environments/{env_id}/scans", response_model=list[ScanRead])
async def list_scans(env_id: int, db: AsyncSession = Depends(get_db)) -> list[Scan]:
    result = await db.execute(
        select(Scan).where(Scan.environment_id == env_id).order_by(Scan.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/scans", response_model=list[ScanWithEnvRead])
async def list_all_scans(
    env_id: int | None = Query(default=None, description="Filter by environment id"),
    from_date: datetime | None = Query(
        default=None, alias="from", description="ISO datetime; ``created_at >= from``"
    ),
    to_date: datetime | None = Query(
        default=None, alias="to", description="ISO datetime; ``created_at <= to``"
    ),
    status: ScanStatus | None = Query(default=None, description="Filter by status"),
    db: AsyncSession = Depends(get_db),
) -> list[ScanWithEnvRead]:
    """Cross-environment scan history for the reports page.

    Each row is enriched with ``environment_name`` and ``finding_count``
    (looked up from the joined Report row, ``None`` when no report exists yet).
    """
    query = select(Scan).order_by(Scan.created_at.desc())
    if env_id is not None:
        query = query.where(Scan.environment_id == env_id)
    if from_date is not None:
        query = query.where(Scan.created_at >= from_date)
    if to_date is not None:
        query = query.where(Scan.created_at <= to_date)
    if status is not None:
        query = query.where(Scan.status == status)

    scans = list((await db.execute(query)).scalars().all())
    if not scans:
        return []

    env_ids = list({s.environment_id for s in scans})
    env_rows = (
        (await db.execute(select(Environment).where(Environment.id.in_(env_ids)))).scalars().all()
    )
    env_name_by_id = {e.id: e.name for e in env_rows}

    scan_ids = [s.id for s in scans]
    report_rows = (
        (await db.execute(select(Report).where(Report.scan_id.in_(scan_ids)))).scalars().all()
    )
    finding_count_by_scan = {r.scan_id: len(r.findings or []) for r in report_rows}

    return [
        ScanWithEnvRead(
            **ScanRead.model_validate(s).model_dump(),
            environment_name=env_name_by_id.get(s.environment_id),
            finding_count=finding_count_by_scan.get(s.id),
        )
        for s in scans
    ]


@router.get("/scans/{scan_id}", response_model=ScanRead)
async def get_scan(scan_id: int, db: AsyncSession = Depends(get_db)) -> Scan:
    scan = await db.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan


@router.get("/scans/{scan_id}/report", response_model=ReportRead)
async def get_report(scan_id: int, db: AsyncSession = Depends(get_db)) -> Report:
    result = await db.execute(select(Report).where(Report.scan_id == scan_id))
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="Report not yet available — scan may still be running or failed",
        )
    return report


@router.get("/scans/{scan_id}/digest")
async def get_digest(scan_id: int, db: AsyncSession = Depends(get_db)) -> dict | None:
    """The pre-processed digest fed to the LLM. Excluded from ScanRead so the
    list/detail responses stay small; fetched on demand by the report page."""
    scan = await db.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan.digest


@router.get("/scans/{scan_id}/raw-data")
async def get_raw_data(scan_id: int, db: AsyncSession = Depends(get_db)) -> dict | None:
    """Raw Kubecost responses (allocation / prior_allocation / assets /
    savings) captured by the worker. Excluded from ScanRead because the
    payload can be up to 256 KB; the report page fetches on demand.

    Returns 404 if the scan does not exist, 409 if the scan has not reached
    a terminal completed state (no raw_data to return)."""
    scan = await db.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    if scan.status != ScanStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"Scan {scan_id} is {scan.status.value}, not completed",
        )
    return scan.raw_data
