"""Tests for the Kubecost client.

Uses ``httpx.MockTransport`` injected via the client's ``transport`` parameter
so the real network is never touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.services.kubecost import (
    COST_FIELDS,
    SENTINEL_NAMES,
    AllocationName,
    KubecostAuthError,
    KubecostClient,
    KubecostNotFoundError,
    KubecostTimeoutError,
    KubecostUnreachableError,
    KubecostUpstreamError,
    parse_allocation_name,
    sum_costs,
    validate_window,
)

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def _client(handler: httpx.MockTransport) -> KubecostClient:
    return KubecostClient(
        base_url="http://kubecost.example.com:9090",
        auth_token="test-token",
        transport=handler,
    )


# -- Helpers: cost summing ---------------------------------------------------


def test_cost_fields_covers_all_cost_keys() -> None:
    assert set(COST_FIELDS) == {
        "cpuCost",
        "ramCost",
        "gpuCost",
        "pvCost",
        "networkCost",
        "loadBalancerCost",
        "sharedCost",
        "externalCost",
    }


def test_sum_costs_handles_missing_and_null_fields() -> None:
    record = {"cpuCost": 10.0, "ramCost": None, "pvCost": "2.5"}
    assert sum_costs(record) == 12.5


def test_sum_costs_full_record_matches_sum() -> None:
    accumulated = _load("kubecost_allocation_accumulated.json")
    api_row = accumulated["data"][0]["production/Deployment/api"]
    expected = (
        api_row["cpuCost"]
        + api_row["ramCost"]
        + api_row["gpuCost"]
        + api_row["pvCost"]
        + api_row["networkCost"]
        + api_row["loadBalancerCost"]
        + api_row["sharedCost"]
        + api_row["externalCost"]
    )
    assert sum_costs(api_row) == pytest.approx(expected)


# -- Helpers: name parsing ---------------------------------------------------


def test_parse_allocation_name_full_three_parts() -> None:
    parsed = parse_allocation_name("data-science/Deployment/jupyter")
    assert parsed == AllocationName(
        namespace="data-science",
        controller_kind="Deployment",
        controller="jupyter",
        raw="data-science/Deployment/jupyter",
        is_sentinel=False,
    )


def test_parse_allocation_name_namespace_only() -> None:
    parsed = parse_allocation_name("data-science")
    assert parsed.namespace == "data-science"
    assert parsed.controller_kind is None
    assert parsed.controller is None
    assert not parsed.is_sentinel


def test_parse_allocation_name_two_parts() -> None:
    parsed = parse_allocation_name("data-science/Deployment")
    assert parsed.namespace == "data-science"
    assert parsed.controller_kind == "Deployment"
    assert parsed.controller is None


@pytest.mark.parametrize("name", sorted(SENTINEL_NAMES))
def test_parse_allocation_name_sentinel(name: str) -> None:
    parsed = parse_allocation_name(name)
    assert parsed.is_sentinel
    assert parsed.namespace is None
    assert parsed.controller_kind is None
    assert parsed.controller is None
    assert parsed.raw == name


# -- Helpers: window validation ----------------------------------------------


@pytest.mark.parametrize("window", ["7d", "30d", "24h", "today", "month", "lastmonth"])
def test_validate_window_accepts_known_values(window: str) -> None:
    assert validate_window(window) == window


@pytest.mark.parametrize("window", ["3d", "1d", "", "yesterday", "2024-01-01,2024-01-02"])
def test_validate_window_rejects_unknown_values(window: str) -> None:
    with pytest.raises(ValueError, match="Invalid window"):
        validate_window(window)


def test_validate_window_accepts_iso_timestamp_range() -> None:
    iso = "2026-04-16T12:00:00Z,2026-04-23T12:00:00Z"
    assert validate_window(iso) == iso


# -- Auth headers ------------------------------------------------------------


async def test_bearer_header_set_when_token_provided() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"version": "2.4.1"})

    client = _client(httpx.MockTransport(handler))
    await client.test_connection()
    assert captured["authorization"] == "Bearer test-token"


async def test_no_auth_header_when_token_none() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"version": "2.4.1"})

    client = KubecostClient(
        base_url="http://kubecost.example.com",
        auth_token=None,
        transport=httpx.MockTransport(handler),
    )
    await client.test_connection()
    assert captured["authorization"] == ""


def test_base_url_trailing_slash_is_stripped() -> None:
    client = KubecostClient(base_url="http://kubecost.example.com:9090/")
    assert client.base_url == "http://kubecost.example.com:9090"


# -- test_connection ---------------------------------------------------------


async def test_test_connection_happy_path_returns_version() -> None:
    payload = _load("kubecost_version.json")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/model/version"
        return httpx.Response(200, json=payload)

    result = await _client(httpx.MockTransport(handler)).test_connection()
    assert result.ok is True
    assert result.kubecost_version == "2.4.1"
    assert result.latency_ms is not None and result.latency_ms >= 0


async def test_test_connection_reads_nested_version_field() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"version": "2.5.0"}})

    result = await _client(httpx.MockTransport(handler)).test_connection()
    assert result.ok is True
    assert result.kubecost_version == "2.5.0"


async def test_test_connection_falls_back_to_cluster_info_on_version_404() -> None:
    paths_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths_seen.append(request.url.path)
        if request.url.path == "/model/version":
            return httpx.Response(404, text="not found")
        return httpx.Response(
            200,
            json={"code": 200, "data": {"version": "1.34", "name": "cluster-one"}},
        )

    result = await _client(httpx.MockTransport(handler)).test_connection()
    assert paths_seen == ["/model/version", "/model/clusterInfo"]
    assert result.ok is True
    assert result.kubecost_version == "1.34"


async def test_test_connection_fails_when_neither_version_endpoint_exists() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    result = await _client(httpx.MockTransport(handler)).test_connection()
    assert result.ok is False
    assert "no version endpoint" in result.message


async def test_test_connection_returns_graceful_failure_on_5xx() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream prom down")

    result = await _client(httpx.MockTransport(handler)).test_connection()
    assert result.ok is False
    assert "Prometheus" in result.message


async def test_test_connection_returns_graceful_failure_on_connect_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name resolution failed")

    result = await _client(httpx.MockTransport(handler)).test_connection()
    assert result.ok is False
    assert "cannot reach" in result.message


# -- Error mapping -----------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "exc_type", "fragment"),
    [
        (401, KubecostAuthError, "invalid or missing token"),
        (403, KubecostAuthError, "lacks permissions"),
        (404, KubecostNotFoundError, "endpoint not found"),
        (502, KubecostUpstreamError, "Prometheus unavailable"),
        (503, KubecostUpstreamError, "Prometheus unavailable"),
        (504, KubecostTimeoutError, "query too slow"),
        (500, KubecostUpstreamError, "HTTP 500"),
    ],
)
async def test_get_allocation_maps_status_to_typed_error(
    status: int, exc_type: type[Exception], fragment: str
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="boom")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(exc_type, match=fragment):
        await client.get_allocation()


async def test_local_timeout_maps_to_timeout_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(KubecostTimeoutError, match="timeout"):
        await client.get_allocation()


async def test_connect_error_maps_to_unreachable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(KubecostUnreachableError, match="cannot reach"):
        await client.get_allocation()


async def test_generic_http_error_maps_to_unreachable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("server hung up")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(KubecostUnreachableError, match="http error"):
        await client.get_allocation()


async def test_invalid_json_response_maps_to_upstream() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(KubecostUpstreamError, match="invalid JSON"):
        await client.get_allocation()


# -- get_allocation ----------------------------------------------------------


async def test_get_allocation_passes_expected_query_params() -> None:
    captured: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update({k: list(request.url.params.get_list(k)) for k in request.url.params})
        return httpx.Response(200, json=_load("kubecost_allocation_accumulated.json"))

    await _client(httpx.MockTransport(handler)).get_allocation(window="7d")
    assert captured["window"] == ["7d"]
    assert captured["aggregate"] == ["namespace,controllerKind,controller"]
    assert captured["accumulate"] == ["true"]
    assert captured["step"] == ["1d"]


async def test_get_allocation_accumulated_shape_passthrough() -> None:
    payload = _load("kubecost_allocation_accumulated.json")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    result = await _client(httpx.MockTransport(handler)).get_allocation()
    # accumulate=true → data is a single-element list keyed by aggregate name.
    assert isinstance(result["data"], list)
    assert len(result["data"]) == 1
    aggregates = result["data"][0]
    assert "data-science/Deployment/jupyter" in aggregates
    assert "__idle__" in aggregates
    assert "__unallocated__" in aggregates


async def test_get_allocation_bucketed_shape_passthrough() -> None:
    payload = _load("kubecost_allocation_buckets.json")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    result = await _client(httpx.MockTransport(handler)).get_allocation(accumulate=False)
    # accumulate=false → one dict per time bucket.
    assert len(result["data"]) == 2
    for bucket in result["data"]:
        assert "production/Deployment/api" in bucket
        assert "__idle__" in bucket


async def test_get_allocation_invalid_window_raises_value_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("should not have made a request")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(ValueError):
        await client.get_allocation(window="3d")


# -- get_assets --------------------------------------------------------------


async def test_get_assets_happy_path() -> None:
    payload = _load("kubecost_assets.json")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/model/assets"
        assert request.url.params.get("aggregate") == "type,cluster"
        return httpx.Response(200, json=payload)

    result = await _client(httpx.MockTransport(handler)).get_assets(window="30d")
    assert "Node/eks-prod" in result["data"][0]


async def test_get_assets_invalid_window_raises_value_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("should not have made a request")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(ValueError):
        await client.get_assets(window="forever")


# -- get_savings -------------------------------------------------------------


async def test_get_savings_returns_all_three_endpoints_when_present() -> None:
    fixtures = {
        "/model/savings/requestSizing": _load("kubecost_savings_request_sizing.json"),
        "/model/savings/clusterSizing": _load("kubecost_savings_cluster_sizing.json"),
        "/model/abandonedWorkloads": _load("kubecost_abandoned_workloads.json"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = fixtures.get(request.url.path)
        if body is None:
            return httpx.Response(500, text="unexpected path")
        return httpx.Response(200, json=body)

    result = await _client(httpx.MockTransport(handler)).get_savings(window="7d")
    assert set(result.keys()) == {"request_sizing", "cluster_sizing", "abandoned_workloads"}
    assert result["request_sizing"]["data"][0]["controllerName"] == "jupyter"
    assert result["cluster_sizing"]["data"]["recommendedNodes"] == 4
    assert result["abandoned_workloads"]["data"][0]["controllerName"] == "stale-canary"


async def test_get_savings_skips_individual_404_gracefully() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/model/abandonedWorkloads":
            return httpx.Response(404, text="not enabled")
        return httpx.Response(200, json={"code": 200, "data": []})

    result = await _client(httpx.MockTransport(handler)).get_savings()
    assert result["request_sizing"] == {"code": 200, "data": []}
    assert result["cluster_sizing"] == {"code": 200, "data": []}
    assert result["abandoned_workloads"] is None


async def test_get_savings_propagates_non_404_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/model/savings/clusterSizing":
            return httpx.Response(503, text="prom down")
        return httpx.Response(200, json={"code": 200, "data": []})

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(KubecostUpstreamError):
        await client.get_savings()


async def test_get_savings_invalid_window_raises_value_error() -> None:
    client = _client(httpx.MockTransport(lambda _: pytest.fail("no request expected")))
    with pytest.raises(ValueError):
        await client.get_savings(window="3d")
