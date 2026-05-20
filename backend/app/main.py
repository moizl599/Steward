"""FastAPI entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import environments, health, scans
from app.api import settings as settings_api
from app.api.deps import close_arq_pool
from app.config import get_settings
from app.db import Base, engine
from app.services.kubecost import (
    KubecostAuthError,
    KubecostError,
    KubecostNotFoundError,
    KubecostTimeoutError,
    KubecostUnreachableError,
    KubecostUpstreamError,
)
from app.services.ollama_client import (
    OllamaError,
    OllamaInvalidOutputError,
    OllamaModelNotFoundError,
    OllamaTimeoutError,
    OllamaUnreachableError,
)

settings = get_settings()


def _configure_logging() -> None:
    logging.basicConfig(level=settings.log_level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    # SQLite dev: auto-create tables so a fresh `docker compose up` just works.
    # Postgres production: tables are managed by Alembic — deploy must run
    # `alembic upgrade head` before the API starts. See alembic/versions/.
    # TODO(ops): bake `alembic upgrade head` into the deploy job once the
    # production runbook lands.
    if engine.dialect.name == "sqlite":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    # Seed the RAG corpus if the collection is empty. Failures here must NOT
    # block API startup — workers will surface a more actionable error if the
    # corpus is unavailable when a scan runs.
    try:
        from app.services.rag import RagService

        rag = RagService()
        await rag.ingest_seed_corpus_if_empty("/app/seed")
    except Exception as exc:
        structlog.get_logger().warning("rag_startup_skipped", error=str(exc))

    yield
    await close_arq_pool()


app = FastAPI(
    title="Steward",
    description="Local-first FinOps for Kubernetes. Reads Kubecost data, analyzes with a local LLM.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(environments.router)
app.include_router(scans.router)
app.include_router(settings_api.router)


_KUBECOST_STATUS: dict[type[KubecostError], tuple[int, str]] = {
    KubecostAuthError: (502, "kubecost_auth"),
    KubecostNotFoundError: (502, "kubecost_not_found"),
    KubecostTimeoutError: (504, "kubecost_timeout"),
    KubecostUnreachableError: (502, "kubecost_unreachable"),
    KubecostUpstreamError: (502, "kubecost_upstream"),
}


@app.exception_handler(KubecostError)
async def _kubecost_exception_handler(request: Request, exc: KubecostError) -> JSONResponse:
    for exc_type, (status, code) in _KUBECOST_STATUS.items():
        if isinstance(exc, exc_type):
            return JSONResponse(status_code=status, content={"error": code, "detail": str(exc)})
    return JSONResponse(
        status_code=502,
        content={"error": "kubecost_error", "detail": str(exc)},
    )


_OLLAMA_STATUS: dict[type[OllamaError], tuple[int, str]] = {
    OllamaModelNotFoundError: (422, "ollama_model_not_found"),
    OllamaUnreachableError: (503, "ollama_unreachable"),
    OllamaTimeoutError: (503, "ollama_timeout"),
    OllamaInvalidOutputError: (502, "ollama_invalid_output"),
}


@app.exception_handler(OllamaError)
async def _ollama_exception_handler(request: Request, exc: OllamaError) -> JSONResponse:
    for exc_type, (status, code) in _OLLAMA_STATUS.items():
        if isinstance(exc, exc_type):
            content: dict[str, Any] = {"error": code, "detail": str(exc)}
            if isinstance(exc, OllamaModelNotFoundError):
                content["hint"] = "pull the model via POST /settings/ollama-model"
            return JSONResponse(status_code=status, content=content)
    return JSONResponse(
        status_code=502,
        content={"error": "ollama_error", "detail": str(exc)},
    )


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "steward", "docs": "/docs"}
