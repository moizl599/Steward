"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/app.db"

    # Encryption key for stored Kubecost auth tokens
    secret_key: str = "changeme-generate-a-real-key"

    # Ollama
    ollama_host: str = "http://ollama:11434"
    ollama_model: str = "qwen2.5:7b-instruct"

    # ChromaDB
    chroma_host: str = "chromadb"
    chroma_port: int = 8000

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # CORS
    cors_origins: str = "http://localhost:3000"

    # Logging
    log_level: str = "INFO"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
