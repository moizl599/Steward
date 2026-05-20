"""Ollama integration: structured analysis + model management.

Produces a :class:`ReportContent` from a digest + RAG context. Token usage and
latency from the chat call are returned alongside, so the worker can persist
them on the Report row.

Key behaviors:

- A strict JSON Schema (derived from the ``ReportContent`` Pydantic model and
  flattened to remove ``$defs``/``$ref``) is sent as ``format`` to ``chat()``.
  Older Ollama builds reject schema-as-format; we detect that and retry once
  with ``format="json"`` and rely on Pydantic to validate the output.
- Validation failures get one repair attempt (the model is fed the validation
  error and asked to fix). A second failure raises
  :class:`OllamaInvalidOutputError`.
- The system prompt is loaded from ``app/prompts/system.md`` and cached.
- ``options={"temperature": 0.2, "seed": 42}`` for repeatability.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog
from ollama import AsyncClient
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.schemas import ReportContent
from app.services.report_validator import format_violations_for_prompt, validate_report

log = structlog.get_logger()

# -- Constants ---------------------------------------------------------------

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "system.md"

RAG_SNIPPET_MAX_CHARS = 500
RAG_TOTAL_MAX_CHARS = 2048

CHAT_OPTIONS: dict[str, Any] = {"temperature": 0.2, "seed": 42}


# -- Exceptions --------------------------------------------------------------


class OllamaError(Exception):
    """Base exception for the Ollama client."""


class OllamaUnreachableError(OllamaError):
    """Could not connect to the Ollama server."""


class OllamaTimeoutError(OllamaError):
    """Ollama request timed out."""


class OllamaModelNotFoundError(OllamaError):
    """The requested model is not pulled on this Ollama install."""


class OllamaInvalidOutputError(OllamaError):
    """Model output failed schema validation twice in a row."""


class _FormatUnsupportedError(Exception):
    """Internal sentinel: Ollama rejected the JSON-Schema ``format`` arg."""


# -- Pydantic models ---------------------------------------------------------


class PullProgress(BaseModel):
    status: str
    digest: str | None = None
    total: int | None = None
    completed: int | None = None


class AnalysisResult(BaseModel):
    report: ReportContent
    prompt_tokens: int
    completion_tokens: int
    duration_ms: int
    eval_duration_ns: int
    prompt_eval_duration_ns: int
    # Violations the model could not fix even after one repair round. Empty
    # list ⇒ the report is consistent with the digest. The worker uses this
    # to decide whether to surface a "low-confidence" banner on the report.
    consistency_violations: list[str] = []


# -- System prompt loader ----------------------------------------------------


@lru_cache(maxsize=1)
def _load_system_prompt() -> str:
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"system prompt not found at {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8")


# -- Schema flattening -------------------------------------------------------


def _flatten_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve ``$ref`` → ``$defs`` inline and strip the ``$defs`` block.

    Ollama's ``format`` validator does not always handle ``$defs``/``$ref``.
    Inlining keeps the schema self-contained and portable across versions.
    """
    schema = deepcopy(schema)
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node and len(node) == 1:
                key = node["$ref"].split("/")[-1]
                target = defs.get(key, {})
                return resolve(target)
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)


def _llm_response_schema() -> dict[str, Any]:
    return _flatten_schema(ReportContent.model_json_schema())


# -- User-message construction ----------------------------------------------


def _format_rag(rag_context: list[str]) -> str:
    snippets: list[str] = []
    used_chars = 0
    for snippet in rag_context:
        clipped = snippet[:RAG_SNIPPET_MAX_CHARS]
        if used_chars + len(clipped) > RAG_TOTAL_MAX_CHARS:
            break
        snippets.append(clipped)
        used_chars += len(clipped)
    if not snippets:
        return "(none provided)"
    return "\n".join(f"{i + 1}. {s}" for i, s in enumerate(snippets))


def _build_user_message(digest: dict[str, Any], rag_context: list[str]) -> str:
    digest_json = json.dumps(digest, indent=2, sort_keys=False)
    rag_block = _format_rag(rag_context)
    return (
        "## Cost digest\n"
        f"{digest_json}\n\n"
        "## Reference guidance\n"
        f"{rag_block}\n\n"
        "Produce your analysis as JSON matching the schema."
    )


# -- Error mapping -----------------------------------------------------------


def _map_chat_exception(exc: Exception) -> Exception:
    """Translate an Ollama/httpx exception into our typed hierarchy.

    Returns the exception object — caller decides whether to raise.
    """
    msg = str(exc).lower()
    name = type(exc).__name__.lower()
    if "connecterror" in name or "connection refused" in msg or "connectionerror" in name:
        return OllamaUnreachableError(str(exc))
    if "timeout" in name or "timed out" in msg or "timeout" in msg:
        return OllamaTimeoutError(str(exc))
    if "not found, try pulling" in msg or "model not found" in msg or "model '" in msg:
        return OllamaModelNotFoundError(str(exc))
    if "format" in msg or "schema" in msg:
        return _FormatUnsupportedError(str(exc))
    return OllamaError(str(exc))


# -- Service -----------------------------------------------------------------


class OllamaService:
    def __init__(
        self,
        host: str | None = None,
        model: str | None = None,
        client: AsyncClient | None = None,
    ) -> None:
        if client is not None:
            self.client = client
        else:
            settings = get_settings()
            self.client = AsyncClient(host=host or settings.ollama_host)
        settings = get_settings()
        self.model = model or settings.ollama_model

    # -- Internal: chat with format fallback ---------------------------------

    async def _chat(self, messages: list[dict[str, str]], schema: dict[str, Any]) -> Any:
        try:
            return await self.client.chat(
                model=self.model,
                messages=messages,
                format=schema,
                options=CHAT_OPTIONS,
            )
        except Exception as exc:
            mapped = _map_chat_exception(exc)
            if isinstance(mapped, _FormatUnsupportedError):
                log.info("ollama_schema_format_unsupported_falling_back_to_json")
                try:
                    return await self.client.chat(
                        model=self.model,
                        messages=messages,
                        format="json",
                        options=CHAT_OPTIONS,
                    )
                except Exception as exc2:
                    raise _map_chat_exception(exc2) from exc2
            raise mapped from exc

    # -- Public API ----------------------------------------------------------

    async def analyze(self, digest: dict[str, Any], rag_context: list[str]) -> AnalysisResult:
        system_prompt = _load_system_prompt()
        user_message = _build_user_message(digest, rag_context)
        schema = _llm_response_schema()
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        response = await self._chat(messages, schema)
        raw = response.message.content

        try:
            report = ReportContent.model_validate_json(raw)
        except ValidationError as first_error:
            log.info("ollama_output_invalid_attempting_repair", error=str(first_error)[:200])
            repair_message = (
                "Your previous response failed schema validation. "
                f"Validation error:\n{first_error}\n\n"
                f"Original response:\n{raw[:1500]}\n\n"
                "Return ONLY a valid JSON object matching the schema. "
                "No prose, no markdown fences."
            )
            repair_messages = [
                *messages,
                {"role": "assistant", "content": raw},
                {"role": "user", "content": repair_message},
            ]
            response = await self._chat(repair_messages, schema)
            raw = response.message.content
            try:
                report = ReportContent.model_validate_json(raw)
            except ValidationError as second_error:
                raise OllamaInvalidOutputError(
                    f"validation failed twice: {second_error}; raw output: {raw[:500]}"
                ) from second_error

        # Post-schema consistency check. One repair attempt if the model's
        # prose contradicts the digest; on failure we surface the residual
        # violations rather than blocking the scan — a flawed report with a
        # warning is more useful than no report at all.
        violations = validate_report(report, digest)
        if violations:
            log.info(
                "ollama_report_inconsistent_attempting_repair",
                violations=violations,
            )
            repair_message = (
                "Your previous response contradicts the digest. Specific "
                "issues:\n"
                f"{format_violations_for_prompt(violations)}\n\n"
                "Rewrite the response so every claim is consistent with the "
                "digest, paying close attention to `analysis_hints`. Use the "
                "exact grade and scale names from analysis_hints. Replace any "
                "boilerplate recommendations with specific workload or "
                "namespace names from the digest. Return ONLY a valid JSON "
                "object matching the schema. No prose, no markdown fences."
            )
            repair_messages = [
                *messages,
                {"role": "assistant", "content": raw},
                {"role": "user", "content": repair_message},
            ]
            try:
                response = await self._chat(repair_messages, schema)
                raw = response.message.content
                report = ReportContent.model_validate_json(raw)
                violations = validate_report(report, digest)
            except ValidationError as repair_err:
                # The repaired response is structurally broken. Keep the
                # original (consistent-schema, inconsistent-content) report
                # and record the validation error so the worker can warn.
                log.warning(
                    "ollama_consistency_repair_failed_schema",
                    error=str(repair_err)[:200],
                )

        total_ns = getattr(response, "total_duration", 0) or 0
        return AnalysisResult(
            report=report,
            prompt_tokens=getattr(response, "prompt_eval_count", 0) or 0,
            completion_tokens=getattr(response, "eval_count", 0) or 0,
            duration_ms=int(total_ns // 1_000_000),
            eval_duration_ns=getattr(response, "eval_duration", 0) or 0,
            prompt_eval_duration_ns=getattr(response, "prompt_eval_duration", 0) or 0,
            consistency_violations=violations,
        )

    async def list_models(self) -> list[str]:
        result = await self.client.list()
        return [m.model for m in result.models]

    async def list_models_detailed(self) -> list[dict[str, Any]]:
        """Return one entry per pulled model with ``name``, ``size_bytes``,
        ``family``, ``parameter_size``, ``modified_at``, ``is_default``."""
        try:
            result = await self.client.list()
        except Exception as exc:
            raise _map_chat_exception(exc) from exc
        out: list[dict[str, Any]] = []
        for m in result.models:
            details = getattr(m, "details", None)
            modified_at = getattr(m, "modified_at", None)
            out.append(
                {
                    "name": m.model,
                    "size_bytes": getattr(m, "size", None),
                    "family": getattr(details, "family", None) if details else None,
                    "parameter_size": (
                        getattr(details, "parameter_size", None) if details else None
                    ),
                    "modified_at": modified_at.isoformat()
                    if hasattr(modified_at, "isoformat")
                    else modified_at,
                    "is_default": m.model == self.model,
                }
            )
        return out

    async def pull_model(self, name: str) -> AsyncIterator[PullProgress]:
        try:
            stream = await self.client.pull(model=name, stream=True)
        except Exception as exc:
            raise _map_chat_exception(exc) from exc

        async for event in stream:
            if isinstance(event, dict):
                data = event
            elif hasattr(event, "model_dump"):
                data = event.model_dump()
            else:
                data = {"status": str(event)}
            yield PullProgress(
                status=data.get("status", ""),
                digest=data.get("digest"),
                total=data.get("total"),
                completed=data.get("completed"),
            )
