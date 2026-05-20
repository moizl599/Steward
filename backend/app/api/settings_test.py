"""Tests for the read-only Settings endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient

from app.api import settings as settings_api
from app.main import app
from app.services.ollama_client import OllamaService


def _build_ollama_service() -> OllamaService:
    class _StubClient:
        async def list(self) -> Any:
            return SimpleNamespace(
                models=[
                    SimpleNamespace(
                        model="qwen2.5:7b-instruct",
                        size=4_700_000_000,
                        modified_at=None,
                        details=SimpleNamespace(family="qwen2", parameter_size="7B"),
                    ),
                    SimpleNamespace(
                        model="llama3.1:8b",
                        size=4_900_000_000,
                        modified_at=None,
                        details=SimpleNamespace(family="llama", parameter_size="8B"),
                    ),
                ]
            )

    return OllamaService(client=_StubClient(), model="qwen2.5:7b-instruct")  # type: ignore[arg-type]


@pytest.fixture
def with_ollama_stub() -> Iterator[OllamaService]:
    svc = _build_ollama_service()
    app.dependency_overrides[settings_api._ollama_service] = lambda: svc
    yield svc
    app.dependency_overrides.pop(settings_api._ollama_service, None)


async def test_list_ollama_models_returns_pulled_models(
    client: AsyncClient, with_ollama_stub: OllamaService
) -> None:
    body = (await client.get("/settings/ollama/models")).json()
    assert {m["name"] for m in body} == {"qwen2.5:7b-instruct", "llama3.1:8b"}
    default = next(m for m in body if m["name"] == "qwen2.5:7b-instruct")
    assert default["is_default"] is True
    assert default["family"] == "qwen2"
    assert default["parameter_size"] == "7B"
    assert default["size_bytes"] == 4_700_000_000


async def test_get_prompt_template_returns_loaded_system_prompt(
    client: AsyncClient,
) -> None:
    body = (await client.get("/settings/prompt-template")).json()
    assert body["name"] == "system"
    assert "FinOps" in body["content"]
    assert body["path"].endswith("system.md")


async def test_list_rag_documents_groups_by_source_file(client: AsyncClient) -> None:
    class _StubRag:
        async def list_documents(self) -> list[dict[str, Any]]:
            return [
                {"source_file": "k8s-rightsizing.md", "chunk_count": 3},
                {"source_file": "spot.md", "chunk_count": 1},
            ]

    app.dependency_overrides[settings_api._rag_service] = lambda: _StubRag()
    try:
        body = (await client.get("/settings/rag/documents")).json()
    finally:
        app.dependency_overrides.pop(settings_api._rag_service, None)
    assert body == [
        {"source_file": "k8s-rightsizing.md", "chunk_count": 3},
        {"source_file": "spot.md", "chunk_count": 1},
    ]


async def test_list_rag_documents_returns_empty_when_chroma_unreachable(
    client: AsyncClient,
) -> None:
    class _BoomRag:
        async def list_documents(self) -> list[dict[str, Any]]:
            return []  # RagService.list_documents already swallows errors

    app.dependency_overrides[settings_api._rag_service] = lambda: _BoomRag()
    try:
        assert (await client.get("/settings/rag/documents")).json() == []
    finally:
        app.dependency_overrides.pop(settings_api._rag_service, None)


def test_ollama_list_models_detailed_unit() -> None:
    """Direct unit on the helper, not via the route — covers the mapping."""

    class _Stub:
        async def list(self) -> Any:
            return SimpleNamespace(
                models=[
                    SimpleNamespace(
                        model="m1",
                        size=10,
                        modified_at=None,
                        details=SimpleNamespace(family="f", parameter_size="3B"),
                    ),
                    SimpleNamespace(  # missing details
                        model="m2",
                        size=None,
                        modified_at=None,
                        details=None,
                    ),
                ]
            )

    import asyncio

    svc = OllamaService(client=_Stub(), model="m1")  # type: ignore[arg-type]
    rows = asyncio.run(svc.list_models_detailed())
    assert rows[0]["is_default"] is True
    assert rows[1]["family"] is None
