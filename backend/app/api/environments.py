"""Environment CRUD + connection testing."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Environment, Report, Scan
from app.schemas import (
    ConnectionTestResult,
    EnvironmentCreate,
    EnvironmentRead,
    EnvironmentUpdate,
    LatestScanSummary,
)
from app.services.crypto import decrypt, encrypt
from app.services.kubecost import KubecostClient

router = APIRouter(prefix="/environments", tags=["environments"])


async def _latest_scans_for(db: AsyncSession, env_ids: list[int]) -> dict[int, Scan]:
    """Return ``{environment_id: latest Scan}`` in a single query."""
    if not env_ids:
        return {}
    max_per_env = (
        select(
            Scan.environment_id.label("env_id"),
            func.max(Scan.created_at).label("max_created"),
        )
        .where(Scan.environment_id.in_(env_ids))
        .group_by(Scan.environment_id)
        .subquery()
    )
    rows = await db.execute(
        select(Scan).join(
            max_per_env,
            (Scan.environment_id == max_per_env.c.env_id)
            & (Scan.created_at == max_per_env.c.max_created),
        )
    )
    return {s.environment_id: s for s in rows.scalars().all()}


async def _finding_counts_for(db: AsyncSession, scan_ids: list[int]) -> dict[int, int]:
    """Return ``{scan_id: len(report.findings)}`` for the given scans."""
    if not scan_ids:
        return {}
    rows = (await db.execute(select(Report).where(Report.scan_id.in_(scan_ids)))).scalars().all()
    return {r.scan_id: len(r.findings or []) for r in rows}


def _to_read(
    env: Environment, latest: Scan | None, finding_count: int | None = None
) -> EnvironmentRead:
    summary = (
        LatestScanSummary.model_validate(latest).model_copy(update={"finding_count": finding_count})
        if latest is not None
        else None
    )
    return EnvironmentRead.model_validate(env).model_copy(update={"latest_scan": summary})


@router.get("", response_model=list[EnvironmentRead])
async def list_environments(db: AsyncSession = Depends(get_db)) -> list[EnvironmentRead]:
    envs = list(
        (await db.execute(select(Environment).order_by(Environment.created_at.desc())))
        .scalars()
        .all()
    )
    latest = await _latest_scans_for(db, [e.id for e in envs])
    finding_counts = await _finding_counts_for(db, [s.id for s in latest.values()])
    return [
        _to_read(
            e,
            latest.get(e.id),
            finding_counts.get(latest[e.id].id) if e.id in latest else None,
        )
        for e in envs
    ]


@router.post("", response_model=EnvironmentRead, status_code=status.HTTP_201_CREATED)
async def create_environment(
    payload: EnvironmentCreate, db: AsyncSession = Depends(get_db)
) -> EnvironmentRead:
    env = Environment(
        name=payload.name,
        kubecost_url=str(payload.kubecost_url),
        aws_region=payload.aws_region,
        cluster_name=payload.cluster_name,
        auth_token_encrypted=encrypt(payload.auth_token) if payload.auth_token else None,
    )
    db.add(env)
    await db.commit()
    await db.refresh(env)
    return _to_read(env, None)


@router.get("/{env_id}", response_model=EnvironmentRead)
async def get_environment(env_id: int, db: AsyncSession = Depends(get_db)) -> EnvironmentRead:
    env = await db.get(Environment, env_id)
    if env is None:
        raise HTTPException(status_code=404, detail="Environment not found")
    latest = (await _latest_scans_for(db, [env.id])).get(env.id)
    finding_count = (
        (await _finding_counts_for(db, [latest.id])).get(latest.id) if latest is not None else None
    )
    return _to_read(env, latest, finding_count)


@router.patch("/{env_id}", response_model=EnvironmentRead)
async def update_environment(
    env_id: int, payload: EnvironmentUpdate, db: AsyncSession = Depends(get_db)
) -> EnvironmentRead:
    env = await db.get(Environment, env_id)
    if env is None:
        raise HTTPException(status_code=404, detail="Environment not found")

    data = payload.model_dump(exclude_unset=True)
    if "auth_token" in data:
        token = data.pop("auth_token")
        env.auth_token_encrypted = encrypt(token) if token else None
    if "kubecost_url" in data:
        data["kubecost_url"] = str(data["kubecost_url"])
    for key, value in data.items():
        setattr(env, key, value)

    await db.commit()
    await db.refresh(env)
    latest = (await _latest_scans_for(db, [env.id])).get(env.id)
    finding_count = (
        (await _finding_counts_for(db, [latest.id])).get(latest.id) if latest is not None else None
    )
    return _to_read(env, latest, finding_count)


@router.delete("/{env_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_environment(env_id: int, db: AsyncSession = Depends(get_db)) -> None:
    env = await db.get(Environment, env_id)
    if env is None:
        raise HTTPException(status_code=404, detail="Environment not found")
    await db.delete(env)
    await db.commit()


@router.post("/{env_id}/test-connection", response_model=ConnectionTestResult)
async def test_connection(env_id: int, db: AsyncSession = Depends(get_db)) -> ConnectionTestResult:
    env = await db.get(Environment, env_id)
    if env is None:
        raise HTTPException(status_code=404, detail="Environment not found")

    token = decrypt(env.auth_token_encrypted) if env.auth_token_encrypted else None
    client = KubecostClient(base_url=env.kubecost_url, auth_token=token)
    result = await client.test_connection()

    env.last_connection_check = datetime.now(UTC)
    env.last_connection_ok = result.ok
    env.last_connection_error = None if result.ok else result.message
    await db.commit()

    return result
