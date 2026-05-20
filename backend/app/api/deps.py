"""Shared FastAPI dependencies."""

from arq.connections import ArqRedis, RedisSettings, create_pool

from app.config import get_settings

_arq_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    """Lazy-initialised arq Redis pool, shared across requests."""
    global _arq_pool
    if _arq_pool is None:
        settings = get_settings()
        _arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _arq_pool


async def close_arq_pool() -> None:
    global _arq_pool
    if _arq_pool is not None:
        await _arq_pool.close()
        _arq_pool = None
