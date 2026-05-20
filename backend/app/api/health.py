"""Health check endpoints."""

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict[str, str]:
    """Readiness probe — extend to check DB, Ollama, ChromaDB once those services have client wrappers."""
    return {"status": "ready"}
