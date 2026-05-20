"""Tests for the arq scan worker.

Each test gets its own in-memory SQLite database so the worker's session and
the test's "peek" sessions share state via ``StaticPool``. All upstream
services (Kubecost client, RAG, Ollama) are faked at the boundary so the
pipeline's wiring is exercised end-to-end without the real model.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.environment import Environment
from app.models.report import Report
from app.models.scan import Scan, ScanStatus
from app.schemas import ReportContent
from app.schemas.report import Finding
from app.services.kubecost import KubecostUnreachableError
from app.services.ollama_client import AnalysisResult, OllamaTimeoutError
from app.workers import scan_worker
from app.workers.scan_worker import (
    MAX_RAG_RESULTS,
    RAG_QUERIES,
    RAW_DATA_MAX_BYTES,
    WorkerDeps,
    _build_rag_queries,
    _maybe_truncate_raw_data,
    run_scan,
)

# -- Test DB -----------------------------------------------------------------


@pytest_asyncio.fixture
async def session_maker() -> Any:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield maker
    await engine.dispose()


def _make_session_factory(maker: Any) -> Any:
    @asynccontextmanager
    async def factory() -> Any:
        async with maker() as session:
            yield session

    return factory


@pytest_asyncio.fixture
async def seeded(session_maker: Any) -> dict[str, int]:
    async with session_maker() as session:
        env = Environment(
            name="prod-eks",
            kubecost_url="http://kubecost.example.com",
            aws_region="us-east-1",
            cluster_name="prod-eks",
            auth_token_encrypted=None,
        )
        session.add(env)
        await session.commit()
        await session.refresh(env)
        scan = Scan(environment_id=env.id, status=ScanStatus.QUEUED, window="7d")
        session.add(scan)
        await session.commit()
        await session.refresh(scan)
    return {"env_id": env.id, "scan_id": scan.id}


# -- Fixtures (Kubecost-shaped data) ----------------------------------------


def _allocation_with_idle_workload() -> dict[str, Any]:
    return {
        "data": [
            {
                "prod/Deployment/api": {
                    "name": "prod/Deployment/api",
                    "properties": {"namespace": "prod"},
                    "cpuCoreUsageAverage": 0.02,  # idle
                    "cpuCoreRequestAverage": 1.0,
                    "ramByteUsageAverage": 100_000_000,
                    "ramByteRequestAverage": 2_000_000_000,
                    "cpuCost": 50.0,
                    "ramCost": 30.0,
                    "gpuCost": 0.0,
                    "pvCost": 0.0,
                    "networkCost": 1.0,
                    "loadBalancerCost": 0.0,
                    "sharedCost": 0.0,
                    "externalCost": 0.0,
                }
            }
        ]
    }


def _empty_assets() -> dict[str, Any]:
    return {"data": [{}]}


def _empty_savings() -> dict[str, Any | None]:
    return {"request_sizing": None, "cluster_sizing": None, "abandoned_workloads": None}


def _valid_report() -> ReportContent:
    return ReportContent(
        executive_summary="One idle workload identified worth $81/mo.",
        findings=[
            Finding(
                title="Idle prod API",
                severity="low",
                category="idle_workloads",
                impact_usd=81.0,
                affected_resource="prod/Deployment/api",
                recommendation="Stop or scale to zero outside business hours.",
                rationale="cpu_util 0.02, mem_util 0.05",
            )
        ],
        estimated_monthly_savings_usd=81.0,
    )


def _analysis_result() -> AnalysisResult:
    return AnalysisResult(
        report=_valid_report(),
        prompt_tokens=120,
        completion_tokens=350,
        duration_ms=2500,
        eval_duration_ns=2_000_000_000,
        prompt_eval_duration_ns=500_000_000,
    )


# -- Fakes -------------------------------------------------------------------


PeekHook = Callable[[str], Awaitable[None]]


class FakeKubecost:
    def __init__(
        self,
        allocation: dict[str, Any] | None = None,
        peek: PeekHook | None = None,
        raise_on: tuple[str, Exception] | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._allocation = allocation or _allocation_with_idle_workload()
        self._peek = peek
        self._raise_on = raise_on

    async def _maybe_peek(self, method: str) -> None:
        if self._peek is not None:
            await self._peek(method)

    async def _maybe_raise(self, method: str) -> None:
        if self._raise_on is not None and self._raise_on[0] == method:
            raise self._raise_on[1]

    async def get_allocation(self, **kwargs: Any) -> dict[str, Any]:
        await self._maybe_peek("get_allocation")
        await self._maybe_raise("get_allocation")
        self.calls.append({"method": "get_allocation", **kwargs})
        # Deep-ish copy so each call gets a distinct dict object.
        return json.loads(json.dumps(self._allocation))

    async def get_assets(self, **kwargs: Any) -> dict[str, Any]:
        await self._maybe_peek("get_assets")
        await self._maybe_raise("get_assets")
        self.calls.append({"method": "get_assets", **kwargs})
        return _empty_assets()

    async def get_savings(self, **kwargs: Any) -> dict[str, Any | None]:
        await self._maybe_peek("get_savings")
        await self._maybe_raise("get_savings")
        self.calls.append({"method": "get_savings", **kwargs})
        return _empty_savings()


class FakeRag:
    def __init__(
        self,
        results_per_query: list[list[str]] | None = None,
        peek: PeekHook | None = None,
    ) -> None:
        self._queue = list(results_per_query or [])
        self._peek = peek
        self.queries: list[str] = []

    async def retrieve(self, query: str, k: int = 4) -> list[str]:
        if self._peek is not None:
            await self._peek("retrieve")
        self.queries.append(query)
        if self._queue:
            return self._queue.pop(0)
        return []


class FakeOllama:
    def __init__(
        self,
        model: str = "qwen2.5:7b-instruct",
        result: AnalysisResult | None = None,
        raise_on_analyze: Exception | None = None,
        peek: PeekHook | None = None,
    ) -> None:
        self.model = model
        self._result = result or _analysis_result()
        self._raise = raise_on_analyze
        self._peek = peek
        self.calls: list[tuple[dict[str, Any], list[str]]] = []

    async def analyze(self, digest: dict[str, Any], rag_context: list[str]) -> AnalysisResult:
        if self._peek is not None:
            await self._peek("analyze")
        self.calls.append((digest, rag_context))
        if self._raise is not None:
            raise self._raise
        return self._result


def _make_deps(
    session_maker: Any,
    *,
    kubecost: FakeKubecost | None = None,
    rag: FakeRag | None = None,
    ollama: FakeOllama | None = None,
) -> WorkerDeps:
    return WorkerDeps(
        session_factory=_make_session_factory(session_maker),
        kubecost_factory=lambda env: kubecost or FakeKubecost(),  # type: ignore[return-value]
        rag_service=rag or FakeRag(),  # type: ignore[arg-type]
        ollama_service=ollama or FakeOllama(),  # type: ignore[arg-type]
    )


# -- Direct helper tests -----------------------------------------------------


def test_build_rag_queries_includes_only_populated_categories() -> None:
    digest = {
        "idle_workloads": [{"name": "x"}],
        "over_provisioned": [],
        "pvc_waste": [{"name": "y"}],
        "anomalies": [],
        "savings_signals": {"cluster_sizing": {"monthly_savings_usd": 200}},
    }
    queries = _build_rag_queries(digest)
    assert RAG_QUERIES["idle_workloads"] in queries
    assert RAG_QUERIES["pvc_waste"] in queries
    assert RAG_QUERIES["savings_signals"] in queries
    assert RAG_QUERIES["over_provisioned"] not in queries
    assert RAG_QUERIES["anomalies"] not in queries


def test_build_rag_queries_returns_empty_when_no_findings() -> None:
    assert _build_rag_queries({"idle_workloads": [], "savings_signals": {}}) == []


def test_truncate_raw_data_keeps_small_payload() -> None:
    raw = {"allocation": {"data": [{"a": 1}]}}
    assert _maybe_truncate_raw_data(raw) is raw


def test_truncate_raw_data_replaces_oversized_payload() -> None:
    big = {"chunk": "x" * (RAW_DATA_MAX_BYTES + 1024)}
    out = _maybe_truncate_raw_data(big)
    assert out["truncated"] is True
    assert out["original_bytes"] > RAW_DATA_MAX_BYTES


# -- Happy path -------------------------------------------------------------


async def test_happy_path_completes_scan_and_persists_report(
    session_maker: Any, seeded: dict[str, int]
) -> None:
    deps = _make_deps(session_maker)
    await run_scan({"deps": deps}, seeded["scan_id"])

    async with session_maker() as session:
        scan = await session.get(Scan, seeded["scan_id"])
        assert scan is not None
        assert scan.status == ScanStatus.COMPLETED
        assert scan.started_at is not None
        assert scan.completed_at is not None
        assert scan.error_message is None
        assert scan.total_cost_usd is not None and scan.total_cost_usd > 0
        assert scan.digest is not None
        assert scan.raw_data is not None
        assert "allocation" in scan.raw_data

        report = (await session.execute(Report.__table__.select())).first()
        assert report is not None
        assert report.scan_id == scan.id
        assert "idle workload" in report.executive_summary.lower()
        assert report.model_used == "qwen2.5:7b-instruct"
        assert report.prompt_tokens == 120
        assert report.completion_tokens == 350
        assert report.duration_ms == 2500


async def test_enrich_findings_backfills_from_digest_reference(
    session_maker: Any, seeded: dict[str, int]
) -> None:
    # Two findings: one points at the idle workload via digest_reference and
    # leaves impact/affected_resource unset; the other has no reference and
    # should be persisted unchanged.
    report = ReportContent(
        executive_summary="Two findings to test enrichment.",
        findings=[
            Finding(
                title="Idle workload pointer",
                severity="low",
                category="idle_workloads",
                recommendation="Scale to zero outside business hours.",
                digest_reference="idle_workloads/prod/Deployment/api",
            ),
            Finding(
                title="Cluster-wide note",
                severity="info",
                category="cluster_efficiency",
                recommendation="Review cluster sizing quarterly.",
                digest_reference=None,
            ),
        ],
        estimated_monthly_savings_usd=0.0,
    )
    analysis = AnalysisResult(
        report=report,
        prompt_tokens=10,
        completion_tokens=20,
        duration_ms=100,
        eval_duration_ns=0,
        prompt_eval_duration_ns=0,
    )
    deps = _make_deps(session_maker, ollama=FakeOllama(result=analysis))
    await run_scan({"deps": deps}, seeded["scan_id"])

    async with session_maker() as session:
        row = (await session.execute(Report.__table__.select())).first()
        assert row is not None
        findings = row.findings
        assert len(findings) == 2

        # Pointer-based finding had digest_reference resolved.
        pointed = findings[0]
        assert pointed["impact_usd"] is not None and pointed["impact_usd"] > 0
        assert pointed["affected_resource"] == "prod/Deployment/api"

        # Null-reference finding untouched.
        cluster_wide = findings[1]
        assert cluster_wide["impact_usd"] is None
        assert cluster_wide["affected_resource"] is None


async def test_progress_messages_recorded_in_order(
    session_maker: Any, seeded: dict[str, int]
) -> None:
    snapshots: list[str | None] = []

    async def peek(_method: str) -> None:
        async with session_maker() as session:
            scan = await session.get(Scan, seeded["scan_id"])
            snapshots.append(scan.progress_message if scan else None)

    deps = _make_deps(
        session_maker,
        kubecost=FakeKubecost(peek=peek),
        rag=FakeRag(peek=peek),
        ollama=FakeOllama(peek=peek),
    )
    await run_scan({"deps": deps}, seeded["scan_id"])

    # Each peek captures the committed progress_message right before the call:
    # Kubecost calls happen during phase 2 ("Connecting to Kubecost").
    # RAG retrieve happens during phase 4 ("Retrieving knowledge").
    # Ollama analyze happens during phase 5 ("Analyzing (model: ...)").
    assert "Connecting to Kubecost" in snapshots
    assert "Retrieving knowledge" in snapshots
    assert any(s and s.startswith("Analyzing (model:") for s in snapshots)


# -- Window selection -------------------------------------------------------


async def test_seven_day_window_triggers_prior_allocation_call(
    session_maker: Any, seeded: dict[str, int]
) -> None:
    fake = FakeKubecost()
    deps = _make_deps(session_maker, kubecost=fake)
    await run_scan({"deps": deps}, seeded["scan_id"])
    allocation_calls = [c for c in fake.calls if c["method"] == "get_allocation"]
    assert len(allocation_calls) == 2
    windows = [c["window"] for c in allocation_calls]
    assert "7d" in windows
    # Prior window is an ISO timestamp range.
    assert any("," in w and "T" in w and "Z" in w for w in windows)


async def test_lastmonth_window_skips_prior_allocation_call(
    session_maker: Any,
) -> None:
    async with session_maker() as session:
        env = Environment(
            name="x",
            kubecost_url="http://kubecost.example.com",
            aws_region="us-east-1",
        )
        session.add(env)
        await session.commit()
        await session.refresh(env)
        scan = Scan(environment_id=env.id, status=ScanStatus.QUEUED, window="lastmonth")
        session.add(scan)
        await session.commit()
        await session.refresh(scan)
        scan_id = scan.id

    fake = FakeKubecost()
    deps = _make_deps(session_maker, kubecost=fake)
    await run_scan({"deps": deps}, scan_id)

    allocation_calls = [c for c in fake.calls if c["method"] == "get_allocation"]
    assert len(allocation_calls) == 1
    async with session_maker() as session:
        scan = await session.get(Scan, scan_id)
        assert scan.status == ScanStatus.COMPLETED
        # No anomalies because prior_allocation was empty.
        assert scan.digest["anomalies"] == []


# -- Failure paths ----------------------------------------------------------


async def test_kubecost_error_marks_failed_with_kubecost_prefix(
    session_maker: Any, seeded: dict[str, int]
) -> None:
    fake = FakeKubecost(
        raise_on=("get_allocation", KubecostUnreachableError("cannot reach kubecost")),
    )
    deps = _make_deps(session_maker, kubecost=fake)
    await run_scan({"deps": deps}, seeded["scan_id"])

    async with session_maker() as session:
        scan = await session.get(Scan, seeded["scan_id"])
        assert scan.status == ScanStatus.FAILED
        assert scan.error_message is not None
        assert scan.error_message.startswith("Kubecost: ")
        assert "cannot reach kubecost" in scan.error_message
        assert scan.completed_at is not None


async def test_ollama_error_marks_failed_with_ollama_prefix(
    session_maker: Any, seeded: dict[str, int]
) -> None:
    deps = _make_deps(
        session_maker,
        ollama=FakeOllama(raise_on_analyze=OllamaTimeoutError("read timed out")),
    )
    await run_scan({"deps": deps}, seeded["scan_id"])

    async with session_maker() as session:
        scan = await session.get(Scan, seeded["scan_id"])
        assert scan.status == ScanStatus.FAILED
        assert scan.error_message is not None
        assert scan.error_message.startswith("Ollama: ")


async def test_unexpected_exception_marks_failed_with_unexpected_prefix(
    session_maker: Any, seeded: dict[str, int]
) -> None:
    deps = _make_deps(
        session_maker,
        ollama=FakeOllama(raise_on_analyze=RuntimeError("schema corruption")),
    )
    await run_scan({"deps": deps}, seeded["scan_id"])

    async with session_maker() as session:
        scan = await session.get(Scan, seeded["scan_id"])
        assert scan.status == ScanStatus.FAILED
        assert scan.error_message is not None
        assert scan.error_message.startswith("Unexpected: ")
        assert "schema corruption" in scan.error_message


async def test_run_scan_does_not_reraise_on_failure(
    session_maker: Any, seeded: dict[str, int]
) -> None:
    deps = _make_deps(
        session_maker,
        ollama=FakeOllama(raise_on_analyze=RuntimeError("boom")),
    )
    # Should NOT raise — the worker swallows so arq doesn't retry.
    await run_scan({"deps": deps}, seeded["scan_id"])


# -- Missing rows -----------------------------------------------------------


async def test_missing_scan_id_is_no_op(session_maker: Any) -> None:
    deps = _make_deps(session_maker)
    # Should not raise even though scan_id 99999 doesn't exist.
    await run_scan({"deps": deps}, 99999)


async def test_missing_environment_marks_scan_failed(session_maker: Any) -> None:
    async with session_maker() as session:
        scan = Scan(environment_id=999, status=ScanStatus.QUEUED, window="7d")
        session.add(scan)
        await session.commit()
        await session.refresh(scan)
        scan_id = scan.id
    deps = _make_deps(session_maker)
    await run_scan({"deps": deps}, scan_id)
    async with session_maker() as session:
        scan = await session.get(Scan, scan_id)
        assert scan.status == ScanStatus.FAILED
        assert "Environment" in (scan.error_message or "")


# -- RAG retrieval ----------------------------------------------------------


async def test_empty_rag_results_does_not_block_completion(
    session_maker: Any, seeded: dict[str, int]
) -> None:
    rag = FakeRag(results_per_query=[])  # always returns []
    ollama = FakeOllama()
    deps = _make_deps(session_maker, rag=rag, ollama=ollama)
    await run_scan({"deps": deps}, seeded["scan_id"])

    async with session_maker() as session:
        scan = await session.get(Scan, seeded["scan_id"])
        assert scan.status == ScanStatus.COMPLETED
    # Ollama still got called with whatever digest + empty (or near-empty) RAG.
    assert len(ollama.calls) == 1
    assert isinstance(ollama.calls[0][1], list)


async def test_rag_results_deduped_and_capped(session_maker: Any, seeded: dict[str, int]) -> None:
    # Trigger TWO RAG categories: idle_workloads (from allocation) and
    # savings_signals (from non-empty cluster_sizing). Each fake query yields
    # a duplicate snippet that should be collapsed.
    class FakeKubecostWithSavings(FakeKubecost):
        async def get_savings(self, **kwargs: Any) -> dict[str, Any | None]:
            self.calls.append({"method": "get_savings", **kwargs})
            return {
                "request_sizing": None,
                "cluster_sizing": {
                    "data": {"monthlySavings": 200.0, "currentNodes": 6, "recommendedNodes": 4}
                },
                "abandoned_workloads": None,
            }

    fake_kc = FakeKubecostWithSavings()
    rag = FakeRag(
        results_per_query=[
            ["[idle.md] dup-snippet", "[idle.md] unique-A"],
            ["[idle.md] dup-snippet", "[savings.md] unique-B"],
        ]
    )
    ollama = FakeOllama()
    deps = _make_deps(session_maker, kubecost=fake_kc, rag=rag, ollama=ollama)
    await run_scan({"deps": deps}, seeded["scan_id"])

    rag_context = ollama.calls[0][1]
    assert len(rag.queries) == 2  # two categories triggered two queries
    assert "[idle.md] dup-snippet" in rag_context
    assert "[idle.md] unique-A" in rag_context
    assert "[savings.md] unique-B" in rag_context
    assert rag_context.count("[idle.md] dup-snippet") == 1
    assert len(rag_context) <= MAX_RAG_RESULTS


# -- Default deps -----------------------------------------------------------


def test_default_deps_constructs_real_services(monkeypatch: pytest.MonkeyPatch) -> None:
    # Stub out the real ChromaDB and Ollama clients so the constructor runs
    # without touching the network.
    import chromadb

    captured: dict[str, Any] = {}

    class _StubChroma:
        def __init__(self, host: str, port: int) -> None:
            captured["chroma"] = (host, port)

    class _StubOllama:
        def __init__(self, host: str) -> None:
            captured["ollama"] = host

    monkeypatch.setattr(chromadb, "HttpClient", _StubChroma)
    monkeypatch.setattr(scan_worker, "OllamaService", lambda: _StubOllamaServiceDummy())
    deps = WorkerDeps.default()
    assert deps.session_factory is scan_worker._default_session_factory
    assert deps.kubecost_factory is scan_worker._default_kubecost_factory


class _StubOllamaServiceDummy:
    model = "stub"

    async def analyze(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


def test_default_kubecost_factory_decrypts_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_decrypt(s: str) -> str:
        captured["decrypted"] = s
        return "secret-plain"

    monkeypatch.setattr(scan_worker, "decrypt", fake_decrypt)
    env = Environment(
        name="x",
        kubecost_url="http://kc.local",
        aws_region="us-east-1",
        auth_token_encrypted="ciphertext",
    )
    client = scan_worker._default_kubecost_factory(env)
    assert captured["decrypted"] == "ciphertext"
    assert client.base_url == "http://kc.local"


def test_default_kubecost_factory_handles_missing_token() -> None:
    env = Environment(
        name="x",
        kubecost_url="http://kc.local",
        aws_region="us-east-1",
        auth_token_encrypted=None,
    )
    client = scan_worker._default_kubecost_factory(env)
    assert client.base_url == "http://kc.local"


# -- Worker on_startup ------------------------------------------------------


async def test_on_startup_populates_ctx_with_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(WorkerDeps, "default", classmethod(lambda cls: "fake-deps"))  # type: ignore[arg-type]
    ctx: dict[str, Any] = {}
    await scan_worker._on_startup(ctx)
    assert ctx["deps"] == "fake-deps"
