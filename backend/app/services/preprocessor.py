"""FinOps digest builder.

Transforms raw Kubecost allocation/assets/savings into a structured digest
ready for the LLM. Bounded to ``DIGEST_MAX_BYTES`` and uses named thresholds
so future tuning is one-constant changes.

Idle vs over-provisioned: a workload that matches the idle rule is omitted
from the over-provisioned bucket — idle is the higher-priority signal.

Sentinels (``__idle__``, ``__unallocated__``, ``__unmounted__``) are aggregate
rollups, never workloads. They are excluded from idle/over-provisioned/etc.
and surfaced separately under ``cluster_breakdown``.

Cluster efficiency formula:
    cpu = sum(cpuCoreUsageAverage) / sum(cpuCoreRequestAverage)
    memory = sum(ramByteUsageAverage) / sum(ramByteRequestAverage)
    overall = provisioned-cost-weighted blend of cpu and memory
The whole digest is a pure function of its inputs — no I/O, no clock.
The ``prior_window`` helper is the only clock-aware function and is kept
separate so the worker can call it independently.

USD values are rounded to 2 decimals; ratios to 3 decimals.

Grounding fields (``cluster_scale``, ``efficiency_grade``, ``analysis_hints``)
are computed up front so the LLM can't contradict the data. They turn
ambiguous numbers (e.g. "is 8% efficiency healthy?") into named buckets the
prompt can refer to by name.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.kubecost import SENTINEL_NAMES, parse_allocation_name, sum_costs

# -- Tunable thresholds ------------------------------------------------------

IDLE_CPU_PCT: float = 0.05
IDLE_MEM_PCT: float = 0.10
OVER_PROV_RATIO: float = 4.0
OVER_PROV_MIN_COST: float = 20.0
ANOMALY_GROWTH: float = 0.20

PVC_OVERPROV_RATIO: float = 1.5
PVC_MIN_COST: float = 5.0

# -- Cluster scale buckets ---------------------------------------------------
#
# Total-cost over the observed window is projected to a monthly run-rate and
# bucketed. The prompt uses these names verbatim so the LLM can't second-guess
# the threshold.
#
# Window normalization is rough (we assume 24h ≈ 1/30 of a month, 7d ≈ 1/4,
# etc.) — this is for prompt grounding, not billing.
SCALE_TRIVIAL_MAX_USD_MONTHLY: float = 50.0  # < $50/mo → "trivial" (lab/dev)
SCALE_SMALL_MAX_USD_MONTHLY: float = 1_000.0  # < $1k/mo → "small"
# Anything else → "production"

# -- Efficiency grade buckets ------------------------------------------------
#
# Overall (provisioned-cost-weighted) cluster efficiency, NOT per-resource.
# The prompt's severity scale references these names by string.
EFFICIENCY_GRADE_HEALTHY_MIN: float = 0.50  # >= 50% -> "healthy"
EFFICIENCY_GRADE_MEDIOCRE_MIN: float = 0.30  # 30-50% -> "mediocre"
EFFICIENCY_GRADE_POOR_MIN: float = 0.15  # 15-30% -> "poor"
# < 15% → "critical"

# -- Truncation --------------------------------------------------------------

DIGEST_MAX_BYTES: int = 8 * 1024
TOP_N_PER_CATEGORY: int = 10
LOW_IMPACT_USD: float = 5.0
NAME_TRUNC_LEN: int = 60

_TRUNCATABLE_KEYS: tuple[str, ...] = (
    "idle_workloads",
    "over_provisioned",
    "pvc_waste",
    "anomalies",
)

# -- Numeric helpers ---------------------------------------------------------

_EPS: float = 1e-9


def _round_usd(value: float) -> float:
    return round(value, 2)


def _round_ratio(value: float) -> float:
    return round(value, 3)


def _utilization(usage: float, request: float) -> float:
    return usage / max(request, _EPS)


def _f(record: dict[str, Any], key: str) -> float:
    return float(record.get(key) or 0.0)


# -- Window helpers ----------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def prior_window(window: str) -> str:
    """Build a Kubecost ISO timestamp range covering the period before ``window``.

    Accepts ``7d``, ``30d``, ``24h``, ``today``, ``month``. Rejects
    ``lastmonth`` — it already points at a backward-looking window so a "prior"
    is not meaningful here.
    """
    if window == "lastmonth":
        raise ValueError("lastmonth has no prior comparison window")
    now = _now()
    if window == "7d":
        end = now - timedelta(days=7)
        start = now - timedelta(days=14)
    elif window == "30d":
        end = now - timedelta(days=30)
        start = now - timedelta(days=60)
    elif window == "24h":
        end = now - timedelta(hours=24)
        start = now - timedelta(hours=48)
    elif window == "today":
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = midnight
        start = midnight - timedelta(days=1)
    elif window == "month":
        first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        first_of_prior_month = (first_of_this_month - timedelta(days=1)).replace(day=1)
        start = first_of_prior_month
        end = first_of_this_month
    else:
        raise ValueError(f"Unsupported window for prior_window: {window}")
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return f"{start.strftime(fmt)},{end.strftime(fmt)}"


# -- Allocation flattening ---------------------------------------------------

_UTIL_KEYS: tuple[str, ...] = (
    "cpuCoreUsageAverage",
    "cpuCoreRequestAverage",
    "ramByteUsageAverage",
    "ramByteRequestAverage",
)

_COST_KEYS: tuple[str, ...] = (
    "cpuCost",
    "ramCost",
    "gpuCost",
    "pvCost",
    "networkCost",
    "loadBalancerCost",
    "sharedCost",
    "externalCost",
)


def _flatten_allocation(allocation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Collapse multi-bucket allocation responses into one record per name.

    Costs are summed across buckets; utilization fields are mean-averaged.
    """
    buckets = allocation.get("data") or []
    flat: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    for bucket in buckets:
        # Kubecost returns ``data: [null]`` for windows where Prometheus has
        # no data (e.g. comparing to a 24h-prior window on a 15-minute-old
        # cluster). Skip empty buckets cleanly instead of crashing.
        if not bucket:
            continue
        for name, record in bucket.items():
            if name not in flat:
                flat[name] = {
                    **{k: _f(record, k) for k in (*_UTIL_KEYS, *_COST_KEYS)},
                    "name": name,
                    "properties": record.get("properties") or {},
                }
                counts[name] = 1
            else:
                existing = flat[name]
                for k in _COST_KEYS:
                    existing[k] += _f(record, k)
                for k in _UTIL_KEYS:
                    existing[k] += _f(record, k)
                counts[name] += 1
    for name, record in flat.items():
        n = counts[name]
        if n > 1:
            for k in _UTIL_KEYS:
                record[k] = record[k] / n
    return flat


def _is_workload(name: str) -> bool:
    return name not in SENTINEL_NAMES


# -- Per-section builders ----------------------------------------------------


def _namespace_costs(workloads: dict[str, dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, record in workloads.items():
        ns = parse_allocation_name(name).namespace or "(unknown)"
        out[ns] = out.get(ns, 0.0) + sum_costs(record)
    return out


def _top_namespaces(namespace_costs: dict[str, float], total_cost: float) -> list[dict[str, Any]]:
    rows = [
        {
            "namespace": ns,
            "cost_usd": _round_usd(cost),
            "share": _round_ratio(cost / total_cost) if total_cost > 0 else 0.0,
        }
        for ns, cost in namespace_costs.items()
    ]
    rows.sort(key=lambda r: (-float(r["cost_usd"]), str(r["namespace"])))
    return rows[:TOP_N_PER_CATEGORY]


def _idle_and_over_provisioned(
    workloads: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    idle: list[dict[str, Any]] = []
    over: list[dict[str, Any]] = []
    for name, record in workloads.items():
        parsed = parse_allocation_name(name)
        # Real-world Kubecost emits slash-padded sentinels like
        # ``__idle__/__idle__/__idle__`` when aggregating with multiple keys.
        # ``_is_workload`` (which filters the bare ``__idle__`` form) doesn't
        # catch those; we filter here on the parsed namespace component too.
        if parsed.namespace in SENTINEL_NAMES:
            continue
        cpu_usage = record["cpuCoreUsageAverage"]
        cpu_req = record["cpuCoreRequestAverage"]
        mem_usage = record["ramByteUsageAverage"]
        mem_req = record["ramByteRequestAverage"]
        cpu_util = _utilization(cpu_usage, cpu_req)
        mem_util = _utilization(mem_usage, mem_req)
        cost = sum_costs(record)
        if cpu_util < IDLE_CPU_PCT and mem_util < IDLE_MEM_PCT:
            idle.append(
                {
                    "name": name,
                    "namespace": parsed.namespace,
                    "controller_kind": parsed.controller_kind,
                    "controller": parsed.controller,
                    "cpu_util": _round_ratio(cpu_util),
                    "mem_util": _round_ratio(mem_util),
                    "cost_usd": _round_usd(cost),
                    "impact_usd": _round_usd(cost),
                }
            )
            continue
        cpu_overprov = cpu_req / max(cpu_usage, _EPS)
        mem_overprov = mem_req / max(mem_usage, _EPS)
        if (
            cpu_overprov >= OVER_PROV_RATIO or mem_overprov >= OVER_PROV_RATIO
        ) and cost >= OVER_PROV_MIN_COST:
            over.append(
                {
                    "name": name,
                    "namespace": parsed.namespace,
                    "controller_kind": parsed.controller_kind,
                    "controller": parsed.controller,
                    "cpu_util": _round_ratio(cpu_util),
                    "mem_util": _round_ratio(mem_util),
                    "cost_usd": _round_usd(cost),
                    "impact_usd": _round_usd(cost * 0.5),
                }
            )
    idle.sort(key=lambda r: (-float(r["impact_usd"]), str(r["name"])))
    over.sort(key=lambda r: (-float(r["impact_usd"]), str(r["name"])))
    return idle, over


def _pvc_waste_from_assets(assets: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for bucket in assets.get("data") or []:
        if not bucket:
            continue
        for name, record in bucket.items():
            if record.get("type") != "Disk":
                continue
            cost = float(record.get("totalCost") or record.get("cost") or 0.0)
            if cost < PVC_MIN_COST:
                continue
            provisioned = float(record.get("bytesProvisioned") or 0.0)
            used = float(record.get("bytesUsed") or 0.0)
            if used <= 0 or provisioned <= 0:
                continue
            ratio = provisioned / used
            if ratio < PVC_OVERPROV_RATIO:
                continue
            utilization = used / provisioned
            out.append(
                {
                    "name": name,
                    "cost_usd": _round_usd(cost),
                    "bytes_provisioned": int(provisioned),
                    "bytes_used": int(used),
                    "utilization": _round_ratio(utilization),
                    "impact_usd": _round_usd(cost * (1 - utilization)),
                }
            )
    out.sort(key=lambda r: (-float(r["impact_usd"]), str(r["name"])))
    return out


def _detect_anomalies(
    workloads: dict[str, dict[str, Any]],
    prior_allocation: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if prior_allocation is None:
        return []
    prior_flat = _flatten_allocation(prior_allocation)
    prior_workloads = {n: r for n, r in prior_flat.items() if _is_workload(n)}
    current = _namespace_costs(workloads)
    prior = _namespace_costs(prior_workloads)
    out: list[dict[str, Any]] = []
    for ns, current_cost in current.items():
        prior_cost = prior.get(ns, 0.0)
        if prior_cost <= 0:
            continue
        growth = (current_cost - prior_cost) / prior_cost
        if growth > ANOMALY_GROWTH:
            out.append(
                {
                    "namespace": ns,
                    "current_cost_usd": _round_usd(current_cost),
                    "prior_cost_usd": _round_usd(prior_cost),
                    "growth_pct": _round_ratio(growth),
                    "impact_usd": _round_usd(current_cost - prior_cost),
                }
            )
    out.sort(key=lambda r: (-float(r["impact_usd"]), str(r["namespace"])))
    return out


def _cluster_efficiency(workloads: dict[str, dict[str, Any]]) -> dict[str, float]:
    cpu_used = sum(r["cpuCoreUsageAverage"] for r in workloads.values())
    cpu_req = sum(r["cpuCoreRequestAverage"] for r in workloads.values())
    mem_used = sum(r["ramByteUsageAverage"] for r in workloads.values())
    mem_req = sum(r["ramByteRequestAverage"] for r in workloads.values())
    cpu_cost = sum(r["cpuCost"] for r in workloads.values())
    mem_cost = sum(r["ramCost"] for r in workloads.values())
    cpu_eff = cpu_used / max(cpu_req, _EPS)
    mem_eff = mem_used / max(mem_req, _EPS)
    total_cost = cpu_cost + mem_cost
    overall = (cpu_eff * cpu_cost + mem_eff * mem_cost) / total_cost if total_cost > 0 else 0.0
    return {
        "cpu": _round_ratio(cpu_eff),
        "memory": _round_ratio(mem_eff),
        "overall": _round_ratio(overall),
    }


def _cluster_breakdown(sentinels: dict[str, dict[str, Any]]) -> dict[str, float]:
    return {
        "idle_pool_cost_usd": _round_usd(sum_costs(sentinels.get("__idle__", {}))),
        "unallocated_cost_usd": _round_usd(sum_costs(sentinels.get("__unallocated__", {}))),
        "unmounted_cost_usd": _round_usd(sum_costs(sentinels.get("__unmounted__", {}))),
    }


# -- Grounding (cluster_scale, efficiency_grade, analysis_hints) -------------


_WINDOW_TO_MONTH_RATIO: dict[str, float] = {
    # Rough projection from observed window → monthly run-rate. Off by a few
    # percent (calendar months ≠ 30 days), but precise enough for bucketing.
    "24h": 30.0,
    "today": 30.0,
    "7d": 30.0 / 7.0,
    "30d": 1.0,
    "month": 1.0,
    "lastmonth": 1.0,
}


def _project_monthly(total_cost_usd: float, window: str) -> float:
    """Project the observed total cost to a 30-day run-rate.

    For ranged ISO windows (used internally when computing prior periods) we
    fall back to ``30d`` semantics — the worst case is we put a borderline
    cluster in the next bucket up.
    """
    multiplier = _WINDOW_TO_MONTH_RATIO.get(window, 1.0)
    return total_cost_usd * multiplier


def _cluster_scale(monthly_cost_usd: float) -> str:
    if monthly_cost_usd < SCALE_TRIVIAL_MAX_USD_MONTHLY:
        return "trivial"
    if monthly_cost_usd < SCALE_SMALL_MAX_USD_MONTHLY:
        return "small"
    return "production"


def _efficiency_grade(overall: float) -> str:
    """Bucket the overall efficiency ratio. Names match the prompt verbatim."""
    if overall >= EFFICIENCY_GRADE_HEALTHY_MIN:
        return "healthy"
    if overall >= EFFICIENCY_GRADE_MEDIOCRE_MIN:
        return "mediocre"
    if overall >= EFFICIENCY_GRADE_POOR_MIN:
        return "poor"
    return "critical"


def _build_grounding(
    *,
    window: str,
    total_cost_usd: float,
    cluster_efficiency: dict[str, float],
    idle_workloads: list[dict[str, Any]],
    over_provisioned: list[dict[str, Any]],
    pvc_waste: list[dict[str, Any]],
    anomalies: list[dict[str, Any]],
) -> tuple[str, str, float, dict[str, Any]]:
    """Produce the grounding block the LLM is required to read first.

    Returns ``(cluster_scale, efficiency_grade, monthly_run_rate_usd, hints)``.
    ``hints`` is a small dict of factual counts the prompt asks the model
    to echo back — used by the post-LLM consistency check.
    """
    monthly = _project_monthly(total_cost_usd, window)
    scale = _cluster_scale(monthly)
    grade = _efficiency_grade(cluster_efficiency.get("overall", 0.0))
    hints = {
        "idle_workload_count": len(idle_workloads),
        "over_provisioned_count": len(over_provisioned),
        "pvc_waste_count": len(pvc_waste),
        "anomaly_count": len(anomalies),
        # Pre-named the headline so the model can quote the grade rather than
        # describing the number.
        "efficiency_grade": grade,
        "cluster_scale": scale,
    }
    return scale, grade, monthly, hints


def _compact_savings(savings: dict[str, Any | None]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    rs = savings.get("request_sizing")
    if rs and rs.get("data"):
        items = rs["data"]
        out["request_sizing"] = {
            "total_monthly_savings_usd": _round_usd(
                sum(float(item.get("monthlySavings") or 0.0) for item in items)
            ),
            "candidate_count": len(items),
        }
    cs = savings.get("cluster_sizing")
    if cs and cs.get("data"):
        d = cs["data"]
        out["cluster_sizing"] = {
            "monthly_savings_usd": _round_usd(float(d.get("monthlySavings") or 0.0)),
            "current_nodes": d.get("currentNodes"),
            "recommended_nodes": d.get("recommendedNodes"),
        }
    aw = savings.get("abandoned_workloads")
    if aw and aw.get("data"):
        items = aw["data"]
        out["abandoned_workloads"] = {
            "total_monthly_cost_usd": _round_usd(
                sum(float(item.get("monthlyCost") or 0.0) for item in items)
            ),
            "count": len(items),
        }
    return out


# -- Size cap ----------------------------------------------------------------


def _digest_size(digest: dict[str, Any]) -> int:
    return len(json.dumps(digest, separators=(",", ":")).encode("utf-8"))


def _enforce_size_cap(digest: dict[str, Any]) -> dict[str, Any]:
    if _digest_size(digest) <= DIGEST_MAX_BYTES:
        return digest

    truncated_counts: dict[str, int] = {}

    # Phase 1: cap each truncatable list at TOP_N_PER_CATEGORY.
    for key in _TRUNCATABLE_KEYS:
        items = digest.get(key) or []
        if len(items) > TOP_N_PER_CATEGORY:
            truncated_counts[key] = len(items)
            digest[key] = items[:TOP_N_PER_CATEGORY]
    digest["truncated"] = True
    digest["truncated_counts"] = truncated_counts
    if _digest_size(digest) <= DIGEST_MAX_BYTES:
        return digest

    # Phase 2: drop low-impact entries.
    for key in _TRUNCATABLE_KEYS:
        items = digest.get(key) or []
        before = len(items)
        kept = [r for r in items if float(r.get("impact_usd") or 0.0) >= LOW_IMPACT_USD]
        if len(kept) < before:
            truncated_counts.setdefault(key, before)
        digest[key] = kept
    digest["truncated_counts"] = truncated_counts
    if _digest_size(digest) <= DIGEST_MAX_BYTES:
        return digest

    # Phase 3: shorten long names with an ellipsis suffix.
    for key in _TRUNCATABLE_KEYS:
        for r in digest.get(key) or []:
            name = r.get("name")
            if isinstance(name, str) and len(name) > NAME_TRUNC_LEN:
                r["name"] = name[: NAME_TRUNC_LEN - 1] + "…"
    return digest


# -- Public API --------------------------------------------------------------


def build_digest(
    allocation: dict[str, Any],
    prior_allocation: dict[str, Any] | None,
    assets: dict[str, Any],
    savings: dict[str, Any | None],
    window: str,
) -> dict[str, Any]:
    """Build a compact, structured digest of cluster cost data for the LLM.

    Pure function: no clock, no I/O. The worker is responsible for fetching
    ``prior_allocation`` (use :func:`prior_window` to compute the range).
    """
    flat = _flatten_allocation(allocation)
    workloads = {n: r for n, r in flat.items() if _is_workload(n)}
    sentinels = {n: r for n, r in flat.items() if not _is_workload(n)}

    total_cost = sum(sum_costs(r) for r in flat.values())
    namespace_costs = _namespace_costs(workloads)
    idle_workloads, over_provisioned = _idle_and_over_provisioned(workloads)
    pvc_waste = _pvc_waste_from_assets(assets)
    anomalies = _detect_anomalies(workloads, prior_allocation)
    cluster_efficiency = _cluster_efficiency(workloads)

    cluster_scale, efficiency_grade, monthly_run_rate, analysis_hints = _build_grounding(
        window=window,
        total_cost_usd=total_cost,
        cluster_efficiency=cluster_efficiency,
        idle_workloads=idle_workloads,
        over_provisioned=over_provisioned,
        pvc_waste=pvc_waste,
        anomalies=anomalies,
    )

    digest: dict[str, Any] = {
        "window": window,
        "total_cost_usd": _round_usd(total_cost),
        # Grounding block — the prompt requires the LLM to consult these before
        # writing the executive summary. Names are stable and machine-checked
        # by the worker's post-LLM consistency validator.
        "monthly_run_rate_usd": _round_usd(monthly_run_rate),
        "cluster_scale": cluster_scale,
        "efficiency_grade": efficiency_grade,
        "analysis_hints": analysis_hints,
        "cluster_efficiency": cluster_efficiency,
        "cluster_breakdown": _cluster_breakdown(sentinels),
        "top_namespaces_by_cost": _top_namespaces(namespace_costs, total_cost),
        "idle_workloads": idle_workloads,
        "over_provisioned": over_provisioned,
        "pvc_waste": pvc_waste,
        "anomalies": anomalies,
        "savings_signals": _compact_savings(savings),
        "truncated": False,
        "truncated_counts": {},
    }

    return _enforce_size_cap(digest)
