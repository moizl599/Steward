"""Tests for the cross-environment scan list endpoint."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.environment import Environment
from app.models.report import Report
from app.models.scan import Scan, ScanStatus


@pytest_asyncio.fixture
async def two_envs(db_session: AsyncSession) -> tuple[Environment, Environment]:
    a = Environment(name="prod", kubecost_url="http://kc-a", aws_region="us-east-1")
    b = Environment(name="staging", kubecost_url="http://kc-b", aws_region="us-west-2")
    db_session.add_all([a, b])
    await db_session.commit()
    await db_session.refresh(a)
    await db_session.refresh(b)
    return a, b


async def _seed_scans(
    db_session: AsyncSession, env: Environment, statuses: list[ScanStatus]
) -> list[Scan]:
    scans: list[Scan] = []
    base = datetime.now(UTC) - timedelta(days=3)
    for i, st in enumerate(statuses):
        s = Scan(
            environment_id=env.id,
            status=st,
            window="24h",
            total_cost_usd=10.0 + i,
            created_at=base + timedelta(hours=i),
        )
        db_session.add(s)
        scans.append(s)
    await db_session.commit()
    for s in scans:
        await db_session.refresh(s)
    return scans


async def test_list_all_scans_returns_descending_with_env_name(
    client: AsyncClient,
    db_session: AsyncSession,
    two_envs: tuple[Environment, Environment],
) -> None:
    a, b = two_envs
    await _seed_scans(db_session, a, [ScanStatus.COMPLETED, ScanStatus.RUNNING])
    await _seed_scans(db_session, b, [ScanStatus.COMPLETED])

    body = (await client.get("/scans")).json()
    assert len(body) == 3
    # Most recent first.
    assert body[0]["environment_name"] in {"prod", "staging"}
    # All rows have env name + finding_count keys.
    for row in body:
        assert "environment_name" in row
        assert "finding_count" in row


async def test_list_all_scans_filters_by_env_id(
    client: AsyncClient,
    db_session: AsyncSession,
    two_envs: tuple[Environment, Environment],
) -> None:
    a, b = two_envs
    await _seed_scans(db_session, a, [ScanStatus.COMPLETED])
    await _seed_scans(db_session, b, [ScanStatus.COMPLETED, ScanStatus.FAILED])

    body = (await client.get(f"/scans?env_id={a.id}")).json()
    assert len(body) == 1
    assert body[0]["environment_id"] == a.id


async def test_list_all_scans_filters_by_status(
    client: AsyncClient,
    db_session: AsyncSession,
    two_envs: tuple[Environment, Environment],
) -> None:
    a, _ = two_envs
    await _seed_scans(db_session, a, [ScanStatus.COMPLETED, ScanStatus.FAILED, ScanStatus.QUEUED])

    body = (await client.get("/scans?status=failed")).json()
    assert len(body) == 1
    assert body[0]["status"] == "failed"


async def test_list_all_scans_filters_by_date_range(
    client: AsyncClient,
    db_session: AsyncSession,
    two_envs: tuple[Environment, Environment],
) -> None:
    a, _ = two_envs
    base = datetime.now(UTC)
    older = Scan(
        environment_id=a.id,
        status=ScanStatus.COMPLETED,
        window="7d",
        created_at=base - timedelta(days=10),
    )
    newer = Scan(
        environment_id=a.id,
        status=ScanStatus.COMPLETED,
        window="7d",
        created_at=base - timedelta(days=1),
    )
    db_session.add_all([older, newer])
    await db_session.commit()

    iso = (base - timedelta(days=5)).isoformat()
    body = (await client.get(f"/scans?from={iso}")).json()
    assert len(body) == 1


async def test_list_all_scans_attaches_finding_count_from_report(
    client: AsyncClient,
    db_session: AsyncSession,
    two_envs: tuple[Environment, Environment],
) -> None:
    a, _ = two_envs
    [scan] = await _seed_scans(db_session, a, [ScanStatus.COMPLETED])
    report = Report(
        scan_id=scan.id,
        executive_summary="ok",
        findings=[
            {"title": "f1", "severity": "info", "category": "x", "recommendation": "y"},
            {"title": "f2", "severity": "low", "category": "x", "recommendation": "y"},
        ],
        model_used="qwen2.5:7b-instruct",
    )
    db_session.add(report)
    await db_session.commit()

    body = (await client.get("/scans")).json()
    assert body[0]["finding_count"] == 2


async def test_list_all_scans_returns_empty_when_no_match(client: AsyncClient) -> None:
    assert (await client.get("/scans")).json() == []


# -- GET /scans/{id}/report: observability fields ---------------------------


async def test_get_report_exposes_duration_and_token_fields(
    client: AsyncClient,
    db_session: AsyncSession,
    two_envs: tuple[Environment, Environment],
) -> None:
    a, _ = two_envs
    [scan] = await _seed_scans(db_session, a, [ScanStatus.COMPLETED])
    report = Report(
        scan_id=scan.id,
        executive_summary="ok",
        findings=[],
        model_used="qwen2.5:7b-instruct",
        estimated_monthly_savings_usd=0.0,
        duration_ms=11_400,
        prompt_tokens=2_481,
        completion_tokens=612,
    )
    db_session.add(report)
    await db_session.commit()

    body = (await client.get(f"/scans/{scan.id}/report")).json()
    assert body["duration_ms"] == 11_400
    assert body["prompt_tokens"] == 2_481
    assert body["completion_tokens"] == 612
    assert body["model_used"] == "qwen2.5:7b-instruct"


async def test_get_report_returns_null_observability_when_unset(
    client: AsyncClient,
    db_session: AsyncSession,
    two_envs: tuple[Environment, Environment],
) -> None:
    a, _ = two_envs
    [scan] = await _seed_scans(db_session, a, [ScanStatus.COMPLETED])
    report = Report(
        scan_id=scan.id,
        executive_summary="legacy row",
        findings=[],
        model_used="qwen2.5:7b-instruct",
        estimated_monthly_savings_usd=None,
        # duration_ms / prompt_tokens / completion_tokens deliberately unset.
    )
    db_session.add(report)
    await db_session.commit()

    body = (await client.get(f"/scans/{scan.id}/report")).json()
    assert body["duration_ms"] is None
    assert body["prompt_tokens"] is None
    assert body["completion_tokens"] is None
