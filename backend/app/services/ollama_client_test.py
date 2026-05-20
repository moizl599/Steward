"""Tests for the Ollama client and prompt loader."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.schemas import ReportContent
from app.services import ollama_client as oc
from app.services.ollama_client import (
    AnalysisResult,
    OllamaInvalidOutputError,
    OllamaModelNotFoundError,
    OllamaService,
    OllamaTimeoutError,
    OllamaUnreachableError,
    PullProgress,
    _flatten_schema,
    _format_rag,
    _llm_response_schema,
    _load_system_prompt,
)

# -- Fakes -------------------------------------------------------------------


def _make_response(
    content: str,
    *,
    prompt_eval_count: int = 120,
    eval_count: int = 350,
    total_duration: int = 2_500_000_000,
    eval_duration: int = 2_000_000_000,
    prompt_eval_duration: int = 500_000_000,
) -> SimpleNamespace:
    return SimpleNamespace(
        message=SimpleNamespace(content=content),
        prompt_eval_count=prompt_eval_count,
        eval_count=eval_count,
        total_duration=total_duration,
        eval_duration=eval_duration,
        prompt_eval_duration=prompt_eval_duration,
    )


def _valid_report_json() -> str:
    return json.dumps(
        {
            "executive_summary": "Cluster spend is concentrated in production. Two findings.",
            "findings": [
                {
                    "title": "Idle jupyter notebook",
                    "severity": "low",
                    "category": "idle_workloads",
                    "impact_usd": 32.65,
                    "affected_resource": "data-science/Deployment/jupyter",
                    "recommendation": "Stop the workload outside of working hours.",
                    "rationale": "cpu_util 0.045, mem_util 0.062 over 7d.",
                },
            ],
            "estimated_monthly_savings_usd": 32.65,
        }
    )


class FakeAsyncClient:
    def __init__(self) -> None:
        self.chat_calls: list[dict[str, Any]] = []
        self._chat_queue: list[Any] = []
        self._pull_events: list[Any] = []
        self._pull_exception: Exception | None = None

    def chat_returns(self, *items: Any) -> None:
        self._chat_queue.extend(items)

    def pull_yields(self, *events: Any) -> None:
        self._pull_events = list(events)

    def pull_raises(self, exc: Exception) -> None:
        self._pull_exception = exc

    async def chat(self, **kwargs: Any) -> Any:
        self.chat_calls.append(kwargs)
        if not self._chat_queue:
            raise AssertionError("no scripted chat response")
        item = self._chat_queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def pull(self, model: str, stream: bool = False) -> Any:
        if self._pull_exception is not None:
            raise self._pull_exception

        events = list(self._pull_events)

        async def _iter() -> Any:
            for ev in events:
                yield ev

        return _iter()


@pytest.fixture
def fake_client() -> FakeAsyncClient:
    return FakeAsyncClient()


@pytest.fixture
def service(fake_client: FakeAsyncClient) -> OllamaService:
    _load_system_prompt.cache_clear()
    return OllamaService(model="qwen2.5:7b-instruct", client=fake_client)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _clear_prompt_cache() -> None:
    _load_system_prompt.cache_clear()


# -- System prompt loader ----------------------------------------------------


def test_load_system_prompt_returns_file_contents() -> None:
    text = _load_system_prompt()
    assert "FinOps" in text


def test_load_system_prompt_contains_required_sections() -> None:
    text = _load_system_prompt()
    for fragment in (
        "## Persona",
        "## Severity scale",
        "## Forbidden phrases",
        "leverage",
        "synergy",
        "best-in-class",
        "robust",
        "seamless",
    ):
        assert fragment in text


def test_load_system_prompt_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    real_read = Path.read_text
    calls = {"n": 0}

    def counting_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == oc.PROMPT_PATH:
            calls["n"] += 1
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    _load_system_prompt.cache_clear()
    _load_system_prompt()
    _load_system_prompt()
    assert calls["n"] == 1


def test_load_system_prompt_missing_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.md"
    monkeypatch.setattr(oc, "PROMPT_PATH", missing)
    _load_system_prompt.cache_clear()
    with pytest.raises(FileNotFoundError, match=r"does-not-exist\.md"):
        _load_system_prompt()


# -- Schema flattening -------------------------------------------------------


def test_flatten_schema_inlines_refs_and_drops_defs() -> None:
    schema = _llm_response_schema()
    serialized = json.dumps(schema)
    assert "$defs" not in schema
    assert "$ref" not in serialized


def test_flatten_schema_resolves_nested_finding_properties() -> None:
    schema = _llm_response_schema()
    findings = schema["properties"]["findings"]
    items_schema = findings["items"]
    # The Finding fields should be inlined right inside items_schema.
    assert "properties" in items_schema
    finding_props = items_schema["properties"]
    for required in ("title", "severity", "category", "recommendation"):
        assert required in finding_props


def test_flatten_schema_preserves_non_ref_structures() -> None:
    schema = _flatten_schema(
        {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "items": {"type": "array", "items": {"type": "integer"}},
            },
        }
    )
    assert schema["properties"]["name"]["minLength"] == 1
    assert schema["properties"]["items"]["items"]["type"] == "integer"


# -- RAG formatting ----------------------------------------------------------


def test_format_rag_empty_returns_placeholder() -> None:
    assert _format_rag([]) == "(none provided)"


def test_format_rag_caps_each_snippet_to_500_chars() -> None:
    long = "a" * 1000
    out = _format_rag([long])
    assert len(out) < 600
    assert "1. " in out


def test_format_rag_caps_total_size() -> None:
    snippets = ["b" * 500] * 10  # 5000 chars before cap
    out = _format_rag(snippets)
    assert len(out) < oc.RAG_TOTAL_MAX_CHARS + 100  # numbering adds a bit


def test_format_rag_numbers_snippets_one_indexed() -> None:
    out = _format_rag(["alpha", "beta", "gamma"])
    assert out.startswith("1. alpha")
    assert "\n2. beta" in out
    assert "\n3. gamma" in out


# -- analyze: happy path -----------------------------------------------------


async def test_analyze_returns_parsed_report_and_token_metrics(
    service: OllamaService, fake_client: FakeAsyncClient
) -> None:
    fake_client.chat_returns(_make_response(_valid_report_json()))

    result = await service.analyze({"total_cost_usd": 215.46}, ["foo", "bar"])

    assert isinstance(result, AnalysisResult)
    assert isinstance(result.report, ReportContent)
    assert result.prompt_tokens == 120
    assert result.completion_tokens == 350
    assert result.duration_ms == 2500
    assert result.eval_duration_ns == 2_000_000_000
    assert result.prompt_eval_duration_ns == 500_000_000


async def test_analyze_sends_expected_request_payload(
    service: OllamaService, fake_client: FakeAsyncClient
) -> None:
    fake_client.chat_returns(_make_response(_valid_report_json()))
    await service.analyze({"total_cost_usd": 100.0}, ["foo"])

    assert len(fake_client.chat_calls) == 1
    call = fake_client.chat_calls[0]
    assert call["model"] == "qwen2.5:7b-instruct"
    messages = call["messages"]
    assert messages[0]["role"] == "system"
    assert "FinOps" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "## Cost digest" in messages[1]["content"]
    assert '"total_cost_usd": 100.0' in messages[1]["content"]
    assert "## Reference guidance" in messages[1]["content"]
    assert "1. foo" in messages[1]["content"]
    assert "JSON matching the schema" in messages[1]["content"]
    assert isinstance(call["format"], dict)
    assert call["options"] == {"temperature": 0.2, "seed": 42}


# -- analyze: format fallback ------------------------------------------------


async def test_analyze_falls_back_to_json_format_on_schema_rejection(
    service: OllamaService, fake_client: FakeAsyncClient
) -> None:
    fake_client.chat_returns(
        Exception("invalid format: schema not supported by this build"),
        _make_response(_valid_report_json()),
    )

    result = await service.analyze({"total_cost_usd": 0}, [])

    assert len(fake_client.chat_calls) == 2
    # First call sent the schema; second used the "json" string.
    assert isinstance(fake_client.chat_calls[0]["format"], dict)
    assert fake_client.chat_calls[1]["format"] == "json"
    assert isinstance(result, AnalysisResult)


# -- analyze: validation + repair --------------------------------------------


async def test_analyze_repairs_invalid_first_response(
    service: OllamaService, fake_client: FakeAsyncClient
) -> None:
    bad_json = '{"executive_summary": "missing findings"}'
    fake_client.chat_returns(
        _make_response(bad_json),
        _make_response(_valid_report_json()),
    )
    result = await service.analyze({"total_cost_usd": 0}, [])

    assert len(fake_client.chat_calls) == 2
    repair_call = fake_client.chat_calls[1]
    repair_messages = repair_call["messages"]
    assert any(
        "failed schema validation" in m["content"] for m in repair_messages if m["role"] == "user"
    )
    assert isinstance(result.report, ReportContent)


async def test_analyze_raises_invalid_output_on_two_failures(
    service: OllamaService, fake_client: FakeAsyncClient
) -> None:
    fake_client.chat_returns(
        _make_response('{"bad": "first"}'),
        _make_response('{"bad": "second"}'),
    )
    with pytest.raises(OllamaInvalidOutputError, match="validation failed twice"):
        await service.analyze({"total_cost_usd": 0}, [])


# -- analyze: typed errors ---------------------------------------------------


async def test_analyze_maps_connect_error_to_unreachable(
    service: OllamaService, fake_client: FakeAsyncClient
) -> None:
    fake_client.chat_returns(httpx.ConnectError("connection refused"))
    with pytest.raises(OllamaUnreachableError):
        await service.analyze({"total_cost_usd": 0}, [])


async def test_analyze_maps_timeout_to_timeout_error(
    service: OllamaService, fake_client: FakeAsyncClient
) -> None:
    class FakeTimeoutError(Exception):
        pass

    FakeTimeoutError.__name__ = "ReadTimeout"
    fake_client.chat_returns(FakeTimeoutError("operation timed out"))
    with pytest.raises(OllamaTimeoutError):
        await service.analyze({"total_cost_usd": 0}, [])


async def test_analyze_maps_model_not_found_error(
    service: OllamaService, fake_client: FakeAsyncClient
) -> None:
    fake_client.chat_returns(
        Exception("model 'qwen2.5:7b-instruct' not found, try pulling it first")
    )
    with pytest.raises(OllamaModelNotFoundError):
        await service.analyze({"total_cost_usd": 0}, [])


# -- pull_model --------------------------------------------------------------


async def test_pull_model_yields_progress_events_from_dict_stream(
    service: OllamaService, fake_client: FakeAsyncClient
) -> None:
    fake_client.pull_yields(
        {"status": "pulling manifest"},
        {
            "status": "downloading",
            "digest": "sha256:abc",
            "total": 1024,
            "completed": 256,
        },
        {"status": "success"},
    )
    events = [e async for e in service.pull_model("qwen2.5:7b-instruct")]
    assert all(isinstance(e, PullProgress) for e in events)
    assert events[0].status == "pulling manifest"
    assert events[1].digest == "sha256:abc"
    assert events[1].total == 1024
    assert events[1].completed == 256
    assert events[2].status == "success"


async def test_pull_model_handles_pydantic_event_objects(
    service: OllamaService, fake_client: FakeAsyncClient
) -> None:
    class FakeEvent:
        def __init__(self, **data: Any) -> None:
            self._data = data

        def model_dump(self) -> dict[str, Any]:
            return self._data

    fake_client.pull_yields(FakeEvent(status="pulling", total=100, completed=50))
    events = [e async for e in service.pull_model("test-model")]
    assert events[0].status == "pulling"
    assert events[0].total == 100


async def test_pull_model_translates_connection_error(
    service: OllamaService, fake_client: FakeAsyncClient
) -> None:
    fake_client.pull_raises(httpx.ConnectError("cannot reach ollama"))
    with pytest.raises(OllamaUnreachableError):
        async for _ in service.pull_model("test-model"):
            pass


async def test_pull_model_handles_primitive_events(
    service: OllamaService, fake_client: FakeAsyncClient
) -> None:
    fake_client.pull_yields("pulling")
    events = [e async for e in service.pull_model("test-model")]
    assert events[0].status == "pulling"


# -- Other coverage gaps -----------------------------------------------------


def test_map_unrecognized_exception_returns_generic_ollama_error() -> None:
    mapped = oc._map_chat_exception(RuntimeError("something else entirely"))
    assert type(mapped) is oc.OllamaError
    assert "something else" in str(mapped)


async def test_analyze_propagates_when_json_fallback_also_fails(
    service: OllamaService, fake_client: FakeAsyncClient
) -> None:
    fake_client.chat_returns(
        Exception("invalid format: schema not supported"),
        httpx.ConnectError("connection refused"),
    )
    with pytest.raises(OllamaUnreachableError):
        await service.analyze({"total_cost_usd": 0}, [])
    assert len(fake_client.chat_calls) == 2


async def test_list_models_returns_model_names(
    service: OllamaService, fake_client: FakeAsyncClient
) -> None:
    fake_client.list = lambda: _ListResultStub()  # type: ignore[attr-defined]
    names = await service.list_models()
    assert names == ["qwen2.5:7b-instruct", "llama3.1:8b"]


class _ListResultStub:
    def __init__(self) -> None:
        self.models = [
            SimpleNamespace(model="qwen2.5:7b-instruct"),
            SimpleNamespace(model="llama3.1:8b"),
        ]

    def __await__(self):
        async def _aw() -> _ListResultStub:
            return self

        return _aw().__await__()


def test_default_construction_uses_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _StubClient:
        def __init__(self, host: str) -> None:
            captured["host"] = host

    monkeypatch.setattr(oc, "AsyncClient", _StubClient)
    svc = OllamaService()
    assert isinstance(svc.client, _StubClient)
    assert captured["host"]  # populated from settings.ollama_host
    assert svc.model  # populated from settings.ollama_model
