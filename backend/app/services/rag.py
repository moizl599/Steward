"""RAG service backed by ChromaDB + sentence-transformers.

Local-only. Embeddings are computed in-process (``all-MiniLM-L6-v2``, CPU)
and passed to ChromaDB explicitly so its built-in embedding functions can't
silently substitute a different model.

Chunking pipeline:
    1. Split markdown by H2 headers (preserve the header line in each chunk).
    2. Sub-split chunks > ``MAX_CHUNK_TOKENS`` on paragraph boundaries.
    3. Merge chunks < ``MIN_CHUNK_TOKENS`` into the next sibling in the file.

Ingestion is idempotent: chunk IDs are
``sha256(source_file + index + text)[:16]`` and we use ChromaDB ``upsert``.
Re-ingesting unchanged content is a no-op; editing a single paragraph in a
file only updates the affected chunk's ID.

Retrieval returns ``list[str]`` so it stays compatible with
``OllamaService.analyze``'s ``rag_context`` signature. Each result is
prefixed with ``[source_file]`` so the LLM has a citable source.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import structlog

from app.config import get_settings

log = structlog.get_logger()

# -- Constants ---------------------------------------------------------------

COLLECTION_NAME = "finops_kb"

MAX_CHUNK_TOKENS = 512
MIN_CHUNK_TOKENS = 50
CHUNK_OVERLAP_WORDS = 0
MIN_SIMILARITY = 0.30
RAG_RESULT_MAX_CHARS = 600
EMBED_BATCH_SIZE = 32

_TOKEN_RATIO = 1.3  # rough words → tokens scale, good enough for chunking decisions
_H2_PATTERN = re.compile(r"(?m)^##\s+.*$")


# -- Embedder ----------------------------------------------------------------


class _Embedder(Protocol):
    def encode(self, texts: list[str], **kwargs: Any) -> Any: ...


@lru_cache(maxsize=1)
def _get_embedder() -> _Embedder:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer("all-MiniLM-L6-v2", device="cpu")


def _embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = _get_embedder()
    vectors = model.encode(
        texts,
        batch_size=EMBED_BATCH_SIZE,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return [list(map(float, v)) for v in vectors]


# -- Chunking ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Chunk:
    text: str
    source_file: str
    h2_section: str
    chunk_index: int


def _approx_tokens(text: str) -> int:
    return int(len(text.split()) * _TOKEN_RATIO)


def _split_by_h2(text: str) -> list[tuple[str, str]]:
    """Return ``[(h2_header, body_with_header_preserved), ...]``."""
    matches = list(_H2_PATTERN.finditer(text))
    sections: list[tuple[str, str]] = []
    if not matches:
        if text.strip():
            sections.append(("", text.strip()))
        return sections
    if matches[0].start() > 0:
        prologue = text[: matches[0].start()].strip()
        if prologue:
            sections.append(("", prologue))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.start() : end].strip()
        sections.append((m.group(0).strip(), body))
    return sections


def _subsplit_paragraphs(body: str, header: str) -> list[str]:
    """Split a too-long body on paragraph boundaries, accumulating into chunks."""
    paragraphs = [p for p in re.split(r"\n\s*\n", body) if p.strip()]
    chunks: list[str] = []
    prefix = f"{header}\n\n" if header else ""
    buffer = prefix
    for p in paragraphs:
        candidate = buffer + p + "\n\n"
        if _approx_tokens(candidate) > MAX_CHUNK_TOKENS and buffer.strip() != prefix.strip():
            chunks.append(buffer.rstrip())
            buffer = prefix + p + "\n\n"
        else:
            buffer = candidate
    if buffer.strip() and buffer.strip() != prefix.strip():
        chunks.append(buffer.rstrip())
    return chunks


def chunk_file(path: Path) -> list[Chunk]:
    """Apply the H2 split → too-big subsplit → too-small merge pipeline to ``path``."""
    text = path.read_text(encoding="utf-8")
    raw: list[tuple[str, str]] = []
    for header, body in _split_by_h2(text):
        if _approx_tokens(body) > MAX_CHUNK_TOKENS:
            for piece in _subsplit_paragraphs(body, header):
                raw.append((header, piece))
        else:
            raw.append((header, body))

    merged: list[tuple[str, str]] = []
    i = 0
    while i < len(raw):
        section, current = raw[i]
        while _approx_tokens(current) < MIN_CHUNK_TOKENS and i + 1 < len(raw):
            i += 1
            current = current + "\n\n" + raw[i][1]
            if not section and raw[i][0]:
                section = raw[i][0]
        merged.append((section, current))
        i += 1

    return [
        Chunk(text=t, source_file=path.name, h2_section=s, chunk_index=idx)
        for idx, (s, t) in enumerate(merged)
    ]


# -- ID hashing --------------------------------------------------------------


def _chunk_id(source_file: str, index: int, text: str) -> str:
    h = hashlib.sha256()
    h.update(source_file.encode("utf-8"))
    h.update(b":")
    h.update(str(index).encode("utf-8"))
    h.update(b":")
    h.update(text.encode("utf-8"))
    return h.hexdigest()[:16]


# -- Service -----------------------------------------------------------------


class RagService:
    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            from chromadb import HttpClient

            settings = get_settings()
            client = HttpClient(host=settings.chroma_host, port=settings.chroma_port)
        self._client = client

    def _collection(self) -> Any:
        return self._client.get_or_create_collection(
            COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    async def ingest_seed_corpus(self, seed_dir: Path | str) -> int:
        seed_path = Path(seed_dir)
        if not seed_path.exists():
            log.warning("rag_seed_dir_missing", path=str(seed_path))
            return 0
        files = sorted(p for p in seed_path.glob("*.md") if p.name != "SEED_TODO.md")
        if not files:
            log.warning("rag_seed_dir_empty", path=str(seed_path))
            return 0

        all_chunks: list[Chunk] = []
        for f in files:
            all_chunks.extend(chunk_file(f))

        if not all_chunks:
            log.info("rag_no_chunks_to_ingest")
            return 0

        ids = [_chunk_id(c.source_file, c.chunk_index, c.text) for c in all_chunks]
        texts = [c.text for c in all_chunks]
        metadatas = [
            {
                "source_file": c.source_file,
                "h2_section": c.h2_section,
                "chunk_index": c.chunk_index,
            }
            for c in all_chunks
        ]
        embeddings = _embed(texts)

        collection = self._collection()
        collection.upsert(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        log.info("rag_ingested", chunk_count=len(all_chunks), files=len(files))
        return len(all_chunks)

    async def ingest_seed_corpus_if_empty(self, seed_dir: Path | str) -> int:
        try:
            collection = self._collection()
            existing = collection.count()
        except Exception as exc:
            log.error("rag_collection_unavailable", error=str(exc))
            return 0
        if existing > 0:
            log.info("rag_seed_already_ingested", count=existing)
            return 0
        try:
            return await self.ingest_seed_corpus(seed_dir)
        except Exception as exc:
            log.error("rag_startup_ingest_failed", error=str(exc))
            return 0

    async def list_documents(self) -> list[dict[str, Any]]:
        """Group ingested chunks by ``source_file``, returning name + chunk_count.

        Returns ``[]`` if Chroma is unreachable or the collection is empty."""
        try:
            collection = self._collection()
            payload = collection.get(include=["metadatas"])
        except Exception as exc:
            log.error("rag_list_documents_failed", error=str(exc))
            return []
        metadatas = payload.get("metadatas") or []
        counts: dict[str, int] = {}
        for meta in metadatas:
            if not meta:
                continue
            source = meta.get("source_file") or "unknown"
            counts[source] = counts.get(source, 0) + 1
        return [
            {"source_file": name, "chunk_count": count} for name, count in sorted(counts.items())
        ]

    async def retrieve(self, query: str, k: int = 4) -> list[str]:
        try:
            collection = self._collection()
        except Exception as exc:
            log.error("rag_collection_unavailable", error=str(exc))
            return []

        query_embedding = _embed([query])
        if not query_embedding:
            return []

        try:
            result = collection.query(
                query_embeddings=query_embedding,
                n_results=k,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            log.error("rag_query_failed", error=str(exc))
            return []

        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0] or [{}] * len(documents)
        distances = (result.get("distances") or [[]])[0] or [1.0] * len(documents)

        out: list[str] = []
        for text, meta, distance in zip(documents, metadatas, distances, strict=False):
            similarity = 1.0 - float(distance)
            if similarity < MIN_SIMILARITY:
                continue
            source = (meta or {}).get("source_file", "unknown")
            formatted = f"[{source}] {text}"[:RAG_RESULT_MAX_CHARS]
            out.append(formatted)
        return out
