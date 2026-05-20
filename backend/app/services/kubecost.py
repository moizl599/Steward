"""Kubecost API client with typed exceptions and structured response helpers.

Endpoints used:
    GET /model/version
    GET /model/allocation
    GET /model/assets
    GET /model/savings/requestSizing
    GET /model/savings/clusterSizing
    GET /model/abandonedWorkloads

Response shape quirks handled here:
- /model/allocation returns ``data`` as a list. With ``accumulate=true`` the
  list has one element (a dict keyed by aggregate name). With
  ``accumulate=false`` the list has one dict per time bucket. We pass the raw
  payload through; the preprocessor walks both shapes uniformly.
- The aggregate ``name`` field is slash-joined when multiple keys are
  requested (e.g. ``"data-science/Deployment/jupyter"``). Use
  :func:`parse_allocation_name`.
- Sentinel names ``__idle__``, ``__unallocated__``, ``__unmounted__`` are not
  parsed but are flagged via ``AllocationName.is_sentinel``.
- Per-row totals are computed by summing :data:`COST_FIELDS`. Kubecost's
  ``totalCost`` exists but is not always populated.

Docs: https://docs.kubecost.com/apis
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from app.schemas import ConnectionTestResult

log = structlog.get_logger()


# -- Cost fields --------------------------------------------------------------

COST_FIELDS: tuple[str, ...] = (
    "cpuCost",
    "ramCost",
    "gpuCost",
    "pvCost",
    "networkCost",
    "loadBalancerCost",
    "sharedCost",
    "externalCost",
)


def sum_costs(record: dict[str, Any]) -> float:
    return sum(float(record.get(field) or 0.0) for field in COST_FIELDS)


# -- Aggregate name parsing ---------------------------------------------------

SENTINEL_NAMES: frozenset[str] = frozenset({"__idle__", "__unallocated__", "__unmounted__"})


@dataclass(frozen=True, slots=True)
class AllocationName:
    namespace: str | None
    controller_kind: str | None
    controller: str | None
    raw: str
    is_sentinel: bool


def parse_allocation_name(name: str) -> AllocationName:
    """Parse an aggregate name like ``"data-science/Deployment/jupyter"``.

    Sentinel names are returned with ``is_sentinel=True`` and parts left as None.
    """
    if name in SENTINEL_NAMES:
        return AllocationName(None, None, None, name, True)
    parts = name.split("/")
    namespace = parts[0] if parts else None
    controller_kind = parts[1] if len(parts) > 1 else None
    controller = parts[2] if len(parts) > 2 else None
    return AllocationName(namespace, controller_kind, controller, name, False)


# -- Window validation --------------------------------------------------------

VALID_WINDOWS: frozenset[str] = frozenset({"7d", "30d", "24h", "today", "month", "lastmonth"})

# ISO 8601 timestamp range: ``2026-04-16T12:00:00Z,2026-04-23T12:00:00Z``.
# Used by the scan worker for prior-window comparisons.
_ISO_RANGE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z,\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
)


def validate_window(window: str) -> str:
    if window in VALID_WINDOWS:
        return window
    if _ISO_RANGE_RE.match(window):
        return window
    valid = ", ".join(sorted(VALID_WINDOWS))
    raise ValueError(
        f"Invalid window '{window}'. Must be one of: {valid}, or an ISO timestamp range."
    )


# -- Exceptions ---------------------------------------------------------------


class KubecostError(Exception):
    """Base exception for the Kubecost client."""


class KubecostAuthError(KubecostError):
    """401/403 — token missing, invalid, or insufficient."""


class KubecostUpstreamError(KubecostError):
    """502/503 or other unexpected response — usually Prometheus-side."""


class KubecostTimeoutError(KubecostError):
    """504 or local timeout — query too slow."""


class KubecostUnreachableError(KubecostError):
    """Network-level connection failure."""


class KubecostNotFoundError(KubecostError):
    """404 — endpoint disabled on this Kubecost install."""


# -- Client -------------------------------------------------------------------


class KubecostClient:
    """Minimal async client for the Kubecost REST API."""

    def __init__(
        self,
        base_url: str,
        auth_token: str | None = None,
        connection_timeout: float = 30.0,
        data_timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers: dict[str, str] = {}
        if auth_token:
            self._headers["Authorization"] = f"Bearer {auth_token}"
        self._connection_timeout = connection_timeout
        self._data_timeout = data_timeout
        self._transport = transport

    async def _request(
        self,
        path: str,
        params: dict[str, Any] | None,
        timeout: float,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
                response = await client.get(url, headers=self._headers, params=params)
        except httpx.TimeoutException as e:
            raise KubecostTimeoutError(f"timeout calling {path}: {e}") from e
        except httpx.ConnectError as e:
            raise KubecostUnreachableError(f"cannot reach {url}: {e}") from e
        except httpx.HTTPError as e:
            raise KubecostUnreachableError(f"http error calling {url}: {e}") from e
        return self._handle_response(response, path)

    @staticmethod
    def _handle_response(response: httpx.Response, path: str) -> Any:
        status = response.status_code
        if status == 200:
            try:
                return response.json()
            except ValueError as e:
                raise KubecostUpstreamError(f"invalid JSON from {path}: {e}") from e
        if status == 401:
            raise KubecostAuthError("invalid or missing token")
        if status == 403:
            raise KubecostAuthError("token lacks permissions")
        if status == 404:
            raise KubecostNotFoundError(f"endpoint not found: {path}")
        if status in (502, 503):
            raise KubecostUpstreamError("Prometheus unavailable")
        if status == 504:
            raise KubecostTimeoutError("query too slow; narrow window or aggregation")
        raise KubecostUpstreamError(f"HTTP {status} from {path}: {response.text[:200]}")

    async def test_connection(self) -> ConnectionTestResult:
        """Ping a known-cheap Kubecost endpoint. Never raises.

        Tries ``/model/version`` first (canonical on older Kubecost), falls
        back to ``/model/clusterInfo`` (modern 1.x/2.x cost-analyzer builds).
        Both expose a ``version`` field.
        """
        start = time.perf_counter()
        last_error: KubecostError | None = None
        for path in ("/model/version", "/model/clusterInfo"):
            try:
                data = await self._request(path, params=None, timeout=self._connection_timeout)
                latency_ms = int((time.perf_counter() - start) * 1000)
                version = data.get("version") or (data.get("data") or {}).get("version")
                return ConnectionTestResult(
                    ok=True,
                    message="Connected",
                    kubecost_version=version,
                    latency_ms=latency_ms,
                )
            except KubecostNotFoundError as e:
                last_error = e
                continue
            except KubecostError as e:
                latency_ms = int((time.perf_counter() - start) * 1000)
                log.warning("kubecost_connection_failed", error=str(e))
                return ConnectionTestResult(ok=False, message=str(e), latency_ms=latency_ms)
        latency_ms = int((time.perf_counter() - start) * 1000)
        message = (
            f"no version endpoint available: {last_error}"
            if last_error
            else "no version endpoint available"
        )
        return ConnectionTestResult(ok=False, message=message, latency_ms=latency_ms)

    async def get_allocation(
        self,
        window: str = "7d",
        aggregate: str = "namespace,controllerKind,controller",
        accumulate: bool = True,
        step: str = "1d",
    ) -> dict[str, Any]:
        validate_window(window)
        params = {
            "window": window,
            "aggregate": aggregate,
            "accumulate": "true" if accumulate else "false",
            "step": step,
        }
        return await self._request("/model/allocation", params=params, timeout=self._data_timeout)

    async def get_assets(
        self,
        window: str = "7d",
        aggregate: str = "type,cluster",
        accumulate: bool = True,
    ) -> dict[str, Any]:
        validate_window(window)
        params = {
            "window": window,
            "aggregate": aggregate,
            "accumulate": "true" if accumulate else "false",
        }
        return await self._request("/model/assets", params=params, timeout=self._data_timeout)

    async def get_savings(self, window: str = "7d") -> dict[str, Any | None]:
        """Aggregate savings endpoints. 404 on individual endpoints is skipped."""
        validate_window(window)
        endpoints: dict[str, str] = {
            "request_sizing": "/model/savings/requestSizing",
            "cluster_sizing": "/model/savings/clusterSizing",
            "abandoned_workloads": "/model/abandonedWorkloads",
        }
        results: dict[str, Any | None] = {}
        for key, path in endpoints.items():
            try:
                results[key] = await self._request(
                    path, params={"window": window}, timeout=self._data_timeout
                )
            except KubecostNotFoundError:
                log.info("kubecost_savings_endpoint_unavailable", path=path)
                results[key] = None
        return results
