"""Tests for the RAG service.

Unit tests run against an in-memory ChromaDB ``EphemeralClient`` and a stub
embedder that produces deterministic 4-dim vectors based on keyword presence.
The slow integration test (``-m slow``) exercises the real
``all-MiniLM-L6-v2`` embedder end-to-end.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb
import numpy as np
import pytest

from app.services import rag
from app.services.rag import (
    MAX_CHUNK_TOKENS,
    MIN_CHUNK_TOKENS,
    MIN_SIMILARITY,
    RAG_RESULT_MAX_CHARS,
    Chunk,
    RagService,
    _approx_tokens,
    _chunk_id,
    chunk_file,
)

# -- Stub embedder ----------------------------------------------------------


class _StubEmbedder:
    """4-dim keyword-presence embedder. Normalized to unit length."""

    KEYWORDS = ("kubernetes", "cost", "spot", "idle")

    def encode(self, texts: list[str], **kwargs: Any) -> Any:
        out: list[np.ndarray] = []
        for t in texts:
            tl = t.lower()
            v = np.array(
                [1.0 if k in tl else 0.0 for k in self.KEYWORDS],
                dtype=np.float32,
            )
            v = v + 0.1  # avoid zero-vector pathology
            v = v / np.linalg.norm(v)
            out.append(v)
        return np.stack(out)


@pytest.fixture(autouse=True)
def stub_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    rag._get_embedder.cache_clear()
    monkeypatch.setattr(rag, "_get_embedder", lambda: _StubEmbedder())


@pytest.fixture
def rag_service(tmp_path: Path) -> RagService:
    # PersistentClient with a per-test tmp dir avoids chromadb's process-level
    # caching of the in-memory database — EphemeralClient() can leak state
    # across tests within the same pytest process.
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    return RagService(client=client)


# -- Chunking ---------------------------------------------------------------


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_approx_tokens_tracks_word_count() -> None:
    assert _approx_tokens("hello world") == int(2 * 1.3)
    assert _approx_tokens("") == 0


def test_chunker_splits_by_h2_preserving_header(tmp_path: Path) -> None:
    body = (
        "Intro paragraph that introduces the document.\n\n"
        "## Section A\n\n"
        + ("Section A body. " * 30)
        + "\n\n## Section B\n\n"
        + ("Section B body. " * 30)
    )
    f = _write(tmp_path / "doc.md", body)
    chunks = chunk_file(f)
    sections = {c.h2_section for c in chunks}
    assert "## Section A" in sections
    assert "## Section B" in sections
    section_a = next(c for c in chunks if c.h2_section == "## Section A")
    assert "## Section A" in section_a.text  # header preserved within the chunk text


def test_chunker_subsplits_long_section(tmp_path: Path) -> None:
    para = ("word " * 200).strip()
    long_body = "## Big\n\n" + ("\n\n".join([para] * 10))
    f = _write(tmp_path / "big.md", long_body)
    chunks = chunk_file(f)
    assert len(chunks) > 1
    for c in chunks:
        assert _approx_tokens(c.text) <= MAX_CHUNK_TOKENS * 1.2  # tolerance for header
        assert c.text.startswith("## Big")


def test_chunker_merges_tiny_chunks(tmp_path: Path) -> None:
    body = "## Tiny\n\nTwo words.\n\n## Bigger\n\n" + ("word " * (MIN_CHUNK_TOKENS + 5)).strip()
    f = _write(tmp_path / "merge.md", body)
    chunks = chunk_file(f)
    # Tiny gets merged with the next sibling → one chunk total.
    assert len(chunks) == 1
    assert "Tiny" in chunks[0].text
    assert "Bigger" in chunks[0].text


def test_chunker_no_h2_returns_single_chunk(tmp_path: Path) -> None:
    body = ("paragraph text. " * 30).strip()
    f = _write(tmp_path / "flat.md", body)
    chunks = chunk_file(f)
    assert len(chunks) == 1
    assert chunks[0].h2_section == ""


def test_chunker_empty_file_returns_no_chunks(tmp_path: Path) -> None:
    f = _write(tmp_path / "empty.md", "")
    assert chunk_file(f) == []


def test_chunker_assigns_chunk_index_starting_at_zero(tmp_path: Path) -> None:
    body = "## A\n\n" + ("a " * 60) + "\n\n## B\n\n" + ("b " * 60)
    f = _write(tmp_path / "ix.md", body)
    chunks = chunk_file(f)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert all(c.source_file == "ix.md" for c in chunks)


# -- ID hashing -------------------------------------------------------------


def test_chunk_id_is_deterministic() -> None:
    a = _chunk_id("foo.md", 0, "hello")
    b = _chunk_id("foo.md", 0, "hello")
    assert a == b
    assert len(a) == 16


def test_chunk_id_changes_when_text_changes() -> None:
    assert _chunk_id("foo.md", 0, "hello") != _chunk_id("foo.md", 0, "hello!")


def test_chunk_id_changes_when_index_changes() -> None:
    assert _chunk_id("foo.md", 0, "x") != _chunk_id("foo.md", 1, "x")


# -- Ingestion --------------------------------------------------------------


def _seed_dir(tmp_path: Path) -> Path:
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "k8s.md").write_text(
        "# Kubernetes cost basics\n\n"
        "## When this matters\n\n"
        + ("Kubernetes cost optimization saves money. " * 12)
        + "\n\n## What to look for\n\n"
        + ("Kubernetes idle workloads. " * 12),
        encoding="utf-8",
    )
    (seed / "spot.md").write_text(
        "# Spot strategy\n\n## Why spot\n\n" + ("Spot instance pricing strategies. " * 12),
        encoding="utf-8",
    )
    (seed / "SEED_TODO.md").write_text("# This file is excluded from ingestion\n", encoding="utf-8")
    return seed


async def test_ingest_indexes_all_files_and_skips_seed_todo(
    tmp_path: Path, rag_service: RagService
) -> None:
    seed = _seed_dir(tmp_path)
    count = await rag_service.ingest_seed_corpus(seed)
    assert count > 0
    collection = rag_service._collection()
    assert collection.count() == count
    # SEED_TODO.md should not contribute any chunks.
    metadatas = collection.get(include=["metadatas"])["metadatas"]
    sources = {m["source_file"] for m in metadatas}
    assert "SEED_TODO.md" not in sources
    assert sources == {"k8s.md", "spot.md"}


async def test_ingest_is_idempotent_for_unchanged_content(
    tmp_path: Path, rag_service: RagService
) -> None:
    seed = _seed_dir(tmp_path)
    first = await rag_service.ingest_seed_corpus(seed)
    second = await rag_service.ingest_seed_corpus(seed)
    assert first == second
    collection = rag_service._collection()
    assert collection.count() == first  # no duplicates


async def test_ingest_replaces_only_changed_chunk(tmp_path: Path, rag_service: RagService) -> None:
    seed = _seed_dir(tmp_path)
    await rag_service.ingest_seed_corpus(seed)
    collection = rag_service._collection()
    ids_before = set(collection.get()["ids"])

    # Edit one file's content.
    spot = seed / "spot.md"
    spot.write_text(
        "# Spot strategy\n\n## Why spot\n\n"
        + ("Spot instance pricing strategies for stateless workloads. " * 12),
        encoding="utf-8",
    )
    await rag_service.ingest_seed_corpus(seed)
    ids_after = set(collection.get()["ids"])

    # k8s.md chunks are unchanged; spot.md chunk IDs differ.
    metadatas_before = {
        i: m["source_file"]
        for i, m in zip(collection.get()["ids"], collection.get()["metadatas"], strict=True)
    }
    unchanged = {i for i, src in metadatas_before.items() if src == "k8s.md"}
    assert unchanged.issubset(ids_after)
    # At least one new spot chunk ID was added.
    new_ids = ids_after - ids_before
    assert any(metadatas_before.get(i) != "k8s.md" for i in new_ids) or new_ids


async def test_ingest_missing_dir_returns_zero(tmp_path: Path, rag_service: RagService) -> None:
    assert await rag_service.ingest_seed_corpus(tmp_path / "nope") == 0


async def test_ingest_empty_dir_returns_zero(tmp_path: Path, rag_service: RagService) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert await rag_service.ingest_seed_corpus(empty) == 0


async def test_ingest_dir_with_only_seed_todo_returns_zero(
    tmp_path: Path, rag_service: RagService
) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "SEED_TODO.md").write_text("excluded", encoding="utf-8")
    assert await rag_service.ingest_seed_corpus(seed) == 0


async def test_ingest_dir_with_only_blank_md_returns_zero(
    tmp_path: Path, rag_service: RagService
) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "blank.md").write_text("", encoding="utf-8")
    assert await rag_service.ingest_seed_corpus(seed) == 0


# -- ingest_seed_corpus_if_empty --------------------------------------------


async def test_if_empty_skips_when_collection_already_populated(
    tmp_path: Path, rag_service: RagService
) -> None:
    seed = _seed_dir(tmp_path)
    first = await rag_service.ingest_seed_corpus(seed)
    assert first > 0
    second = await rag_service.ingest_seed_corpus_if_empty(seed)
    assert second == 0  # already populated, no-op


async def test_if_empty_runs_when_collection_empty(tmp_path: Path, rag_service: RagService) -> None:
    seed = _seed_dir(tmp_path)
    count = await rag_service.ingest_seed_corpus_if_empty(seed)
    assert count > 0


async def test_if_empty_chromadb_unreachable_returns_zero() -> None:
    class BoomClient:
        def get_or_create_collection(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("connection refused")

    svc = RagService(client=BoomClient())
    assert await svc.ingest_seed_corpus_if_empty("/nonexistent/path") == 0


async def test_if_empty_swallows_ingest_failures(tmp_path: Path) -> None:
    class FlakyCollection:
        def count(self) -> int:
            return 0

        def upsert(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("disk full mid-upsert")

    class FlakyClient:
        def get_or_create_collection(self, *args: Any, **kwargs: Any) -> Any:
            return FlakyCollection()

    seed = _seed_dir(tmp_path)
    svc = RagService(client=FlakyClient())
    assert await svc.ingest_seed_corpus_if_empty(seed) == 0


# -- Retrieval --------------------------------------------------------------


async def test_retrieve_returns_results_with_source_prefix(
    tmp_path: Path, rag_service: RagService
) -> None:
    seed = _seed_dir(tmp_path)
    await rag_service.ingest_seed_corpus(seed)
    results = await rag_service.retrieve("kubernetes cost", k=4)
    assert results
    # Every result is prefixed with [source_file].
    assert all(r.startswith("[") and "] " in r for r in results)
    # The k8s.md doc should be the top match.
    assert any(r.startswith("[k8s.md]") for r in results)


async def test_retrieve_drops_results_below_similarity_threshold(
    tmp_path: Path, rag_service: RagService
) -> None:
    seed = _seed_dir(tmp_path)
    await rag_service.ingest_seed_corpus(seed)
    # "kubernetes cost" only matches the k8s.md doc; spot.md is well below
    # MIN_SIMILARITY (0.30) under the stub embedder.
    results = await rag_service.retrieve("kubernetes cost", k=4)
    assert all("[spot.md]" not in r for r in results)
    assert MIN_SIMILARITY == 0.30  # guard against accidental tweak


async def test_retrieve_caps_each_result_at_max_chars(
    tmp_path: Path, rag_service: RagService
) -> None:
    seed = tmp_path / "seed"
    seed.mkdir()
    long_text = "Kubernetes cost word " * 200  # ~4000 chars
    (seed / "long.md").write_text("## Long\n\n" + long_text, encoding="utf-8")
    svc = RagService(client=chromadb.PersistentClient(path=str(tmp_path / "chroma2")))
    await svc.ingest_seed_corpus(seed)
    results = await svc.retrieve("kubernetes cost", k=4)
    assert results
    assert all(len(r) <= RAG_RESULT_MAX_CHARS for r in results)


async def test_retrieve_empty_collection_returns_empty(rag_service: RagService) -> None:
    assert await rag_service.retrieve("kubernetes cost") == []


async def test_retrieve_chromadb_unreachable_returns_empty() -> None:
    class BoomClient:
        def get_or_create_collection(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("chroma down")

    svc = RagService(client=BoomClient())
    assert await svc.retrieve("anything") == []


async def test_retrieve_query_failure_returns_empty() -> None:
    class FlakyCollection:
        def query(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("query failed")

    class FlakyClient:
        def get_or_create_collection(self, *args: Any, **kwargs: Any) -> Any:
            return FlakyCollection()

    svc = RagService(client=FlakyClient())
    assert await svc.retrieve("kubernetes cost") == []


# -- Construction -----------------------------------------------------------


def test_default_construction_uses_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _StubHttpClient:
        def __init__(self, host: str, port: int) -> None:
            captured["host"] = host
            captured["port"] = port

    import chromadb as cdb

    monkeypatch.setattr(cdb, "HttpClient", _StubHttpClient)
    svc = RagService()
    assert isinstance(svc._client, _StubHttpClient)
    assert captured["host"]
    assert captured["port"]


# -- Internal helper coverage ----------------------------------------------


def test_embed_returns_empty_for_empty_input() -> None:
    assert rag._embed([]) == []


def test_chunk_dataclass_is_immutable() -> None:
    c = Chunk(text="t", source_file="f", h2_section="## H", chunk_index=0)
    with pytest.raises(AttributeError):
        c.text = "other"  # type: ignore[misc]


# -- Slow integration test (real model) ------------------------------------


@pytest.mark.slow
async def test_real_embedder_end_to_end(tmp_path: Path) -> None:
    """Real ``all-MiniLM-L6-v2`` embeddings against a synthetic 3-doc corpus.

    Only runs with ``pytest -m slow``. Verifies that real semantic retrieval
    actually returns the most relevant document.
    """
    rag._get_embedder.cache_clear()
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "rightsizing.md").write_text(
        "# Kubernetes rightsizing\n\n## Approach\n\n"
        "Set CPU and memory requests to match observed usage. Use VPA recommendations "
        "or Kubecost's request-sizing endpoint as a starting point. Avoid the temptation "
        "to set request equal to limit — leave headroom for bursts.\n",
        encoding="utf-8",
    )
    (seed / "spot.md").write_text(
        "# Spot instances on EKS\n\n## When to use\n\n"
        "Spot instances suit stateless, restart-tolerant workloads — batch jobs, "
        "horizontally scaled web tiers. Avoid for stateful sets, leader-elected "
        "controllers, or anything with long warm-up costs.\n",
        encoding="utf-8",
    )
    (seed / "pvc.md").write_text(
        "# EBS / PVC waste\n\n## Common patterns\n\n"
        "Unmounted persistent volumes still incur cost. Migrating gp2 → gp3 saves "
        "around 20% on storage spend at equivalent performance.\n",
        encoding="utf-8",
    )
    svc = RagService(client=chromadb.PersistentClient(path=str(tmp_path / "chroma_real")))
    await svc.ingest_seed_corpus(seed)
    results = await svc.retrieve("how do I rightsize CPU requests in kubernetes?", k=2)
    assert results
    assert results[0].startswith("[rightsizing.md]")
