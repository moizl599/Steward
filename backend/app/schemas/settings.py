"""Pydantic schemas for the read-only Settings v1 endpoints."""

from pydantic import BaseModel


class OllamaModelInfo(BaseModel):
    name: str
    size_bytes: int | None = None
    family: str | None = None
    parameter_size: str | None = None
    modified_at: str | None = None
    is_default: bool = False


class PromptTemplate(BaseModel):
    name: str
    content: str
    path: str


class RagDocument(BaseModel):
    source_file: str
    chunk_count: int
