"""Tests for environment list/detail endpoints, focused on the embedded
``latest_scan`` field added for the dashboard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.environment import Environment
from app.models.report import Report
from app.models.scan import Scan, ScanStatus


@pytest_asyncio.fixture
async def env(db_session: AsyncSession) -> Environment:
    e = Environment(
        name="prod-eks",
        kubecost_url="http://kubecost.example.com",
        aws_region="us-east-1",
        cluster_name="prod-eks",
    )
    db_session.add(e)
    await db_session.commit()
    await db_session.refresh(e)
    return e


async def test_list_environments_includes_null_latest_scan_when_no_scans(
    client: AsyncClient, env: Environment
) -> None:
    response = await client.get("/environments")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["latest_scan"] is None


async def test_list_environments_returns_most_recent_scan_only(
    client: AsyncClient, db_session: AsyncSession, env: Environment
) -> None:
    older = Scan(
        environment_id=env.id,
        status=ScanStatus.COMPLETED,
        window="7d",
        total_cost_usd=100.0,
        created_at=datetime.now(UTC) - timedelta(days=2),
    )
    newer = Scan(
        environment_id=env.id,
        status=ScanStatus.COMPLETED,
        window="24h",
        total_cost_usd=15.5,
        created_at=datetime.now(UTC),
    )
    db_session.add_all([older, newer])
    await db_session.commit()
    await db_session.refresh(newer)

    body = (await client.get("/environments")).json()
    assert body[0]["latest_scan"]["id"] == newer.id
    assert body[0]["latest_scan"]["window"] == "24h"
    assert body[0]["latest_scan"]["total_cost_usd"] == 15.5


async def test_get_environment_includes_latest_scan(
    client: AsyncClient, db_session: AsyncSession, env: Environment
) -> None:
    s = Scan(environment_id=env.id, status=ScanStatus.RUNNING, window="7d")
    db_session.add(s)
    await db_session.commit()

    body = (await client.get(f"/environments/{env.id}")).json()
    assert body["latest_scan"]["status"] == "running"
    assert body["latest_scan"]["window"] == "7d"


async def test_list_environments_populates_finding_count_from_report(
    client: AsyncClient, db_session: AsyncSession, env: Environment
) -> None:
    scan = Scan(
        environment_id=env.id,
        status=ScanStatus.COMPLETED,
        window="24h",
        total_cost_usd=2.5,
    )
    db_session.add(scan)
    await db_session.commit()
    await db_session.refresh(scan)
    report = Report(
        scan_id=scan.id,
        executive_summary="...",
        findings=[
            {"title": "f1", "severity": "low", "category": "idle_workloads", "recommendation": "x"},
            {
                "title": "f2",
                "severity": "info",
                "category": "cluster_efficiency",
                "recommendation": "y",
            },
            {
                "title": "f3",
                "severity": "info",
                "category": "cluster_efficiency",
                "recommendation": "z",
            },
        ],
        model_used="qwen2.5:7b-instruct",
    )
    db_session.add(report)
    await db_session.commit()

    body = (await client.get("/environments")).json()
    assert body[0]["latest_scan"]["finding_count"] == 3


async def test_list_environments_finding_count_null_for_queued_scan(
    client: AsyncClient, db_session: AsyncSession, env: Environment
) -> None:
    scan = Scan(environment_id=env.id, status=ScanStatus.QUEUED, window="24h")
    db_session.add(scan)
    await db_session.commit()

    body = (await client.get("/environments")).json()
    assert body[0]["latest_scan"]["status"] == "queued"
    assert body[0]["latest_scan"]["finding_count"] is None


async def test_get_environment_populates_finding_count(
    client: AsyncClient, db_session: AsyncSession, env: Environment
) -> None:
    scan = Scan(environment_id=env.id, status=ScanStatus.COMPLETED, window="24h")
    db_session.add(scan)
    await db_session.commit()
    await db_session.refresh(scan)
    report = Report(
        scan_id=scan.id,
        executive_summary="...",
        findings=[
            {"title": "f", "severity": "low", "category": "idle_workloads", "recommendation": "x"}
        ],
        model_used="qwen2.5:7b-instruct",
    )
    db_session.add(report)
    await db_session.commit()

    body = (await client.get(f"/environments/{env.id}")).json()
    assert body["latest_scan"]["finding_count"] == 1


async def test_create_environment_returns_null_latest_scan(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/environments",
        json={
            "name": "fresh",
            "kubecost_url": "http://kubecost.example.com",
            "aws_region": "us-east-1",
        },
    )
    assert response.status_code == 201
    assert response.json()["latest_scan"] is None


async def test_get_digest_returns_scan_digest(
    client: AsyncClient, db_session: AsyncSession, env: Environment
) -> None:
    digest = {"window": "7d", "total_cost_usd": 215.46, "idle_workloads": []}
    s = Scan(
        environment_id=env.id,
        status=ScanStatus.COMPLETED,
        window="7d",
        digest=digest,
    )
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)

    body = (await client.get(f"/scans/{s.id}/digest")).json()
    assert body == digest


async def test_get_digest_returns_null_for_pending_scan(
    client: AsyncClient, db_session: AsyncSession, env: Environment
) -> None:
    s = Scan(environment_id=env.id, status=ScanStatus.QUEUED, window="7d")
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)

    response = await client.get(f"/scans/{s.id}/digest")
    assert response.status_code == 200
    assert response.json() is None


async def test_get_digest_404_for_unknown_scan(client: AsyncClient) -> None:
    response = await client.get("/scans/9999/digest")
    assert response.status_code == 404


async def test_get_raw_data_returns_payload_for_completed_scan(
    client: AsyncClient, db_session: AsyncSession, env: Environment
) -> None:
    raw_data = {
        "allocation": {"data": [{"ns/Deployment/api": {"cpuCost": 1.0}}]},
        "prior_allocation": {"data": []},
        "assets": {"data": [{}]},
        "savings": {"request_sizing": None},
    }
    s = Scan(
        environment_id=env.id,
        status=ScanStatus.COMPLETED,
        window="24h",
        raw_data=raw_data,
    )
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)

    response = await client.get(f"/scans/{s.id}/raw-data")
    assert response.status_code == 200
    assert response.json() == raw_data


async def test_get_raw_data_409_for_non_completed_scan(
    client: AsyncClient, db_session: AsyncSession, env: Environment
) -> None:
    for status in (ScanStatus.QUEUED, ScanStatus.RUNNING, ScanStatus.FAILED):
        s = Scan(environment_id=env.id, status=status, window="7d")
        db_session.add(s)
        await db_session.commit()
        await db_session.refresh(s)

        response = await client.get(f"/scans/{s.id}/raw-data")
        assert response.status_code == 409, status
        assert status.value in response.json()["detail"]


async def test_get_raw_data_404_for_unknown_scan(client: AsyncClient) -> None:
    response = await client.get("/scans/9999/raw-data")
    assert response.status_code == 404
