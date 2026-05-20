"""Read-only settings endpoints (v1).

Edit/write flows are intentionally deferred — see TASKS.md F7 / B7. These
routes power the Settings page and surface enough state for the user to
verify what's pulled, what prompt is in use, and what's in the RAG corpus.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends

from app.schemas import OllamaModelInfo, PromptTemplate, RagDocument
from app.services.ollama_client import (
    PROMPT_PATH,
    OllamaService,
    _load_system_prompt,
)
from app.services.rag import RagService

log = structlog.get_logger()
router = APIRouter(prefix="/settings", tags=["settings"])


def _ollama_service() -> OllamaService:
    return OllamaService()


def _rag_service() -> RagService:
    return RagService()


@router.get("/ollama/models", response_model=list[OllamaModelInfo])
async def list_ollama_models(
    service: OllamaService = Depends(_ollama_service),
) -> list[OllamaModelInfo]:
    """Models pulled on the local Ollama. Errors propagate via the typed
    ``OllamaError`` handler in ``main.py``."""
    raw = await service.list_models_detailed()
    return [OllamaModelInfo(**m) for m in raw]


@router.get("/prompt-template", response_model=PromptTemplate)
async def get_prompt_template() -> PromptTemplate:
    """The active system prompt used by ``OllamaService.analyze``."""
    return PromptTemplate(
        name="system",
        content=_load_system_prompt(),
        path=str(PROMPT_PATH),
    )


@router.get("/rag/documents", response_model=list[RagDocument])
async def list_rag_documents(
    service: RagService = Depends(_rag_service),
) -> list[RagDocument]:
    """Sources currently ingested in the FinOps RAG corpus.

    Returns ``[]`` if Chroma is unreachable rather than 5xx-ing the page —
    the Settings page gracefully degrades.
    """
    raw = await service.list_documents()
    return [RagDocument(**d) for d in raw]
