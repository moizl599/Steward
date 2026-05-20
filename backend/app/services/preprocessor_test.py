"""Tests for the FinOps digest preprocessor."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.services import preprocessor as pp
from app.services.preprocessor import (
    ANOMALY_GROWTH,
    DIGEST_MAX_BYTES,
    EFFICIENCY_GRADE_HEALTHY_MIN,
    EFFICIENCY_GRADE_MEDIOCRE_MIN,
    EFFICIENCY_GRADE_POOR_MIN,
    IDLE_CPU_PCT,
    IDLE_MEM_PCT,
    OVER_PROV_MIN_COST,
    OVER_PROV_RATIO,
    SCALE_SMALL_MAX_USD_MONTHLY,
    SCALE_TRIVIAL_MAX_USD_MONTHLY,
    build_digest,
    prior_window,
)

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def _load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def _savings_bundle() -> dict[str, Any | None]:
    return {
        "request_sizing": _load("kubecost_savings_request_sizing.json"),
        "cluster_sizing": _load("kubecost_savings_cluster_sizing.json"),
        "abandoned_workloads": _load("kubecost_abandoned_workloads.json"),
    }


def _digest_size(digest: dict[str, Any]) -> int:
    return len(json.dumps(digest, separators=(",", ":")).encode("utf-8"))


# -- Thresholds are named constants ------------------------------------------


def test_thresholds_have_documented_values() -> None:
    assert IDLE_CPU_PCT == 0.05
    assert IDLE_MEM_PCT == 0.10
    assert OVER_PROV_RATIO == 4.0
    assert OVER_PROV_MIN_COST == 20.0
    assert ANOMALY_GROWTH == 0.20
    assert SCALE_TRIVIAL_MAX_USD_MONTHLY == 50.0
    assert SCALE_SMALL_MAX_USD_MONTHLY == 1_000.0
    assert EFFICIENCY_GRADE_HEALTHY_MIN == 0.50
    assert EFFICIENCY_GRADE_MEDIOCRE_MIN == 0.30
    assert EFFICIENCY_GRADE_POOR_MIN == 0.15


# -- Grounding (cluster_scale + efficiency_grade) ----------------------------


def test_cluster_scale_trivial_for_tiny_total() -> None:
    # $0.02 over 24h projects to ~$0.60/mo → trivial.
    allocation = {
        "data": [
            {
                "data-science/Deployment/jupyter": {
                    "cpuCoreUsageAverage": 0.001,
                    "cpuCoreRequestAverage": 0.1,
                    "ramByteUsageAverage": 100,
                    "ramByteRequestAverage": 1000,
                    "cpuCost": 0.01,
                    "ramCost": 0.01,
                    "gpuCost": 0,
                    "pvCost": 0,
                    "networkCost": 0,
                    "loadBalancerCost": 0,
                    "sharedCost": 0,
                    "externalCost": 0,
                    "properties": {"namespace": "data-science"},
                }
            }
        ]
    }
    digest = build_digest(allocation, None, {"data": []}, {}, window="24h")
    assert digest["cluster_scale"] == "trivial"
    assert digest["monthly_run_rate_usd"] < SCALE_TRIVIAL_MAX_USD_MONTHLY


def test_cluster_scale_production_for_large_total() -> None:
    # $400 over 24h projects to ~$12k/mo → production.
    allocation = {
        "data": [
            {
                "production/Deployment/api": {
                    "cpuCoreUsageAverage": 1,
                    "cpuCoreRequestAverage": 4,
                    "ramByteUsageAverage": 1e9,
                    "ramByteRequestAverage": 4e9,
                    "cpuCost": 200,
                    "ramCost": 200,
                    "gpuCost": 0,
                    "pvCost": 0,
                    "networkCost": 0,
                    "loadBalancerCost": 0,
                    "sharedCost": 0,
                    "externalCost": 0,
                    "properties": {"namespace": "production"},
                }
            }
        ]
    }
    digest = build_digest(allocation, None, {"data": []}, {}, window="24h")
    assert digest["cluster_scale"] == "production"


def test_efficiency_grade_critical_for_sub_15_percent() -> None:
    # Overall efficiency of ~8% (matches the user's screenshot scenario).
    allocation = {
        "data": [
            {
                "kubecost/Deployment/cost-analyzer": {
                    "cpuCoreUsageAverage": 0.001,
                    "cpuCoreRequestAverage": 0.1,
                    "ramByteUsageAverage": 1e7,
                    "ramByteRequestAverage": 1e8,
                    "cpuCost": 0.01,
                    "ramCost": 0.01,
                    "gpuCost": 0,
                    "pvCost": 0,
                    "networkCost": 0,
                    "loadBalancerCost": 0,
                    "sharedCost": 0,
                    "externalCost": 0,
                    "properties": {"namespace": "kubecost"},
                }
            }
        ]
    }
    digest = build_digest(allocation, None, {"data": []}, {}, window="24h")
    assert digest["efficiency_grade"] == "critical"
    assert digest["analysis_hints"]["efficiency_grade"] == "critical"


def test_efficiency_grade_healthy_for_50_plus_percent() -> None:
    allocation = {
        "data": [
            {
                "production/Deployment/api": {
                    "cpuCoreUsageAverage": 2.5,
                    "cpuCoreRequestAverage": 4,
                    "ramByteUsageAverage": 3e9,
                    "ramByteRequestAverage": 4e9,
                    "cpuCost": 50,
                    "ramCost": 50,
                    "gpuCost": 0,
                    "pvCost": 0,
                    "networkCost": 0,
                    "loadBalancerCost": 0,
                    "sharedCost": 0,
                    "externalCost": 0,
                    "properties": {"namespace": "production"},
                }
            }
        ]
    }
    digest = build_digest(allocation, None, {"data": []}, {}, window="24h")
    assert digest["efficiency_grade"] == "healthy"


def test_analysis_hints_count_idle_and_over_provisioned() -> None:
    allocation = _load("kubecost_allocation_accumulated.json")
    digest = build_digest(allocation, None, _load("kubecost_assets.json"), {}, window="7d")
    hints = digest["analysis_hints"]
    assert hints["idle_workload_count"] == len(digest["idle_workloads"])
    assert hints["over_provisioned_count"] == len(digest["over_provisioned"])
    assert hints["pvc_waste_count"] == len(digest["pvc_waste"])
    assert hints["anomaly_count"] == len(digest["anomalies"])


# -- prior_window ------------------------------------------------------------


@pytest.fixture
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> datetime:
    fixed = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(pp, "_now", lambda: fixed)
    return fixed


def test_prior_window_7d_returns_prior_seven_days(fixed_now: datetime) -> None:
    result = prior_window("7d")
    assert result == "2026-04-16T12:00:00Z,2026-04-23T12:00:00Z"


def test_prior_window_30d(fixed_now: datetime) -> None:
    result = prior_window("30d")
    assert result == "2026-03-01T12:00:00Z,2026-03-31T12:00:00Z"


def test_prior_window_24h(fixed_now: datetime) -> None:
    result = prior_window("24h")
    assert result == "2026-04-28T12:00:00Z,2026-04-29T12:00:00Z"


def test_prior_window_today_compares_against_yesterday(fixed_now: datetime) -> None:
    # Yesterday's full day, ending at today's 00:00 UTC.
    result = prior_window("today")
    assert result == "2026-04-29T00:00:00Z,2026-04-30T00:00:00Z"


def test_prior_window_month_returns_calendar_prior_month(fixed_now: datetime) -> None:
    result = prior_window("month")
    assert result == "2026-03-01T00:00:00Z,2026-04-01T00:00:00Z"


def test_prior_window_lastmonth_rejected() -> None:
    with pytest.raises(ValueError, match="lastmonth"):
        prior_window("lastmonth")


def test_prior_window_unsupported_value_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported window"):
        prior_window("3d")


# -- Snapshot test (purity & determinism) ------------------------------------


def test_digest_matches_checked_in_snapshot() -> None:
    allocation = _load("kubecost_allocation_accumulated.json")
    assets = _load("kubecost_assets.json")
    savings = _savings_bundle()
    digest = build_digest(allocation, None, assets, savings, window="7d")
    expected = _load("digest_snapshot.json")
    assert digest == expected


def test_build_digest_is_pure() -> None:
    allocation = _load("kubecost_allocation_accumulated.json")
    assets = _load("kubecost_assets.json")
    savings = _savings_bundle()
    a = build_digest(allocation, None, assets, savings, window="7d")
    b = build_digest(allocation, None, assets, savings, window="7d")
    assert a == b


# -- Idle vs over-provisioned split ------------------------------------------


def test_idle_workload_appears_in_idle_not_over_provisioned() -> None:
    allocation = _load("kubecost_allocation_accumulated.json")
    digest = build_digest(allocation, None, _load("kubecost_assets.json"), {}, window="7d")
    idle_names = {row["name"] for row in digest["idle_workloads"]}
    over_names = {row["name"] for row in digest["over_provisioned"]}
    assert "data-science/Deployment/jupyter" in idle_names
    assert "data-science/Deployment/jupyter" not in over_names


def test_over_provisioned_workload_appears() -> None:
    allocation = _load("kubecost_allocation_accumulated.json")
    digest = build_digest(allocation, None, _load("kubecost_assets.json"), {}, window="7d")
    over_names = {row["name"] for row in digest["over_provisioned"]}
    assert "production/StatefulSet/postgres" in over_names


def test_kube_proxy_not_flagged_when_below_min_cost() -> None:
    # kube-proxy in fixture is over-prov by ratio but cost < $20.
    allocation = _load("kubecost_allocation_accumulated.json")
    digest = build_digest(allocation, None, _load("kubecost_assets.json"), {}, window="7d")
    over_names = {row["name"] for row in digest["over_provisioned"]}
    assert "kube-system/DaemonSet/kube-proxy" not in over_names


# -- Sentinels handled correctly ---------------------------------------------


def test_sentinels_never_appear_in_workload_lists() -> None:
    allocation = _load("kubecost_allocation_accumulated.json")
    digest = build_digest(allocation, None, _load("kubecost_assets.json"), {}, window="7d")
    for key in ("idle_workloads", "over_provisioned", "anomalies"):
        for row in digest[key]:
            assert row.get("name") not in {"__idle__", "__unallocated__", "__unmounted__"}
            assert row.get("namespace") not in {"__idle__", "__unallocated__", "__unmounted__"}


def test_sentinels_appear_in_cluster_breakdown() -> None:
    allocation = _load("kubecost_allocation_accumulated.json")
    digest = build_digest(allocation, None, _load("kubecost_assets.json"), {}, window="7d")
    cb = digest["cluster_breakdown"]
    assert cb["idle_pool_cost_usd"] == 32.35
    assert cb["unallocated_cost_usd"] == 1.85
    assert cb["unmounted_cost_usd"] == 0.0


def test_sentinels_excluded_from_top_namespaces() -> None:
    allocation = _load("kubecost_allocation_accumulated.json")
    digest = build_digest(allocation, None, _load("kubecost_assets.json"), {}, window="7d")
    namespaces = {row["namespace"] for row in digest["top_namespaces_by_cost"]}
    assert "__idle__" not in namespaces
    assert "__unallocated__" not in namespaces


def test_slash_padded_sentinels_excluded_from_idle_and_over_provisioned() -> None:
    """Regression: real-world Kubecost emits names like
    ``__idle__/__idle__/__idle__`` under multi-key aggregation. The previous
    filter only matched the bare ``__idle__`` form, leaking the padded version
    into the workload lists."""
    allocation = {
        "data": [
            {
                "__idle__/__idle__/__idle__": {
                    "cpuCoreUsageAverage": 0.0,
                    "cpuCoreRequestAverage": 1.0,
                    "ramByteUsageAverage": 0,
                    "ramByteRequestAverage": 1_000_000_000,
                    "cpuCost": 30.0,
                    "ramCost": 20.0,
                    "gpuCost": 0.0,
                    "pvCost": 0.0,
                    "networkCost": 0.0,
                    "loadBalancerCost": 0.0,
                    "sharedCost": 0.0,
                    "externalCost": 0.0,
                    "properties": {"namespace": "__idle__"},
                },
                "__unallocated__/__unallocated__/__unallocated__": {
                    "cpuCoreUsageAverage": 0.0,
                    "cpuCoreRequestAverage": 4.0,
                    "ramByteUsageAverage": 0,
                    "ramByteRequestAverage": 4_000_000_000,
                    "cpuCost": 25.0,
                    "ramCost": 15.0,
                    "gpuCost": 0.0,
                    "pvCost": 0.0,
                    "networkCost": 0.0,
                    "loadBalancerCost": 0.0,
                    "sharedCost": 0.0,
                    "externalCost": 0.0,
                    "properties": {"namespace": "__unallocated__"},
                },
                "production/Deployment/api": {
                    "cpuCoreUsageAverage": 0.5,
                    "cpuCoreRequestAverage": 1.0,
                    "ramByteUsageAverage": 1_000_000_000,
                    "ramByteRequestAverage": 2_000_000_000,
                    "cpuCost": 50.0,
                    "ramCost": 30.0,
                    "gpuCost": 0.0,
                    "pvCost": 0.0,
                    "networkCost": 0.0,
                    "loadBalancerCost": 0.0,
                    "sharedCost": 0.0,
                    "externalCost": 0.0,
                    "properties": {"namespace": "production"},
                },
            }
        ]
    }
    digest = build_digest(allocation, None, {"data": []}, {}, window="24h")

    sentinel_namespaces = {"__idle__", "__unallocated__", "__unmounted__"}
    for key in ("idle_workloads", "over_provisioned"):
        for row in digest[key]:
            assert row.get("namespace") not in sentinel_namespaces, (
                f"sentinel namespace leaked into digest['{key}']: {row}"
            )
            assert not (row.get("name") or "").startswith("__idle__/"), row
            assert not (row.get("name") or "").startswith("__unallocated__/"), row


# -- Cluster efficiency ------------------------------------------------------


def test_cluster_efficiency_uses_documented_formula() -> None:
    allocation = _load("kubecost_allocation_accumulated.json")
    digest = build_digest(allocation, None, _load("kubecost_assets.json"), {}, window="7d")
    eff = digest["cluster_efficiency"]
    # Hand-computed from the four workloads in the fixture.
    assert eff["cpu"] == 0.162
    assert eff["memory"] == 0.312
    assert eff["overall"] == 0.206


def test_cluster_efficiency_handles_empty_workloads() -> None:
    digest = build_digest({"data": []}, None, {"data": []}, {}, window="7d")
    assert digest["cluster_efficiency"] == {"cpu": 0.0, "memory": 0.0, "overall": 0.0}


def test_build_digest_handles_kubecost_null_buckets() -> None:
    """Kubecost returns ``data: [null]`` when Prometheus has no data for the
    requested window (e.g. comparing 24h-prior on a 15-minute-old cluster).
    The preprocessor must not crash on that shape."""
    null_payload: dict[str, Any] = {"data": [None]}
    digest = build_digest(null_payload, null_payload, null_payload, {}, window="24h")
    assert digest["total_cost_usd"] == 0.0
    assert digest["idle_workloads"] == []
    assert digest["over_provisioned"] == []
    assert digest["pvc_waste"] == []
    assert digest["anomalies"] == []


def test_build_digest_mixes_null_and_real_buckets() -> None:
    real_bucket = _allocation_for("prod", 100.0)["data"][0]
    payload: dict[str, Any] = {"data": [None, real_bucket, None]}
    digest = build_digest(payload, None, {"data": []}, {}, window="7d")
    assert digest["total_cost_usd"] > 0
    assert any(row["namespace"] == "prod" for row in digest["top_namespaces_by_cost"])


# -- Anomalies ---------------------------------------------------------------


def _allocation_for(namespace: str, cost: float) -> dict[str, Any]:
    return {
        "data": [
            {
                f"{namespace}/Deployment/api": {
                    "name": f"{namespace}/Deployment/api",
                    "properties": {"namespace": namespace},
                    "cpuCoreUsageAverage": 0.5,
                    "cpuCoreRequestAverage": 1.0,
                    "ramByteUsageAverage": 1_000_000_000,
                    "ramByteRequestAverage": 2_000_000_000,
                    "cpuCost": cost,
                    "ramCost": 0.0,
                    "gpuCost": 0.0,
                    "pvCost": 0.0,
                    "networkCost": 0.0,
                    "loadBalancerCost": 0.0,
                    "sharedCost": 0.0,
                    "externalCost": 0.0,
                }
            }
        ]
    }


def test_anomaly_detected_when_growth_exceeds_threshold() -> None:
    current = _allocation_for("production", 125.0)
    prior = _allocation_for("production", 100.0)  # +25% growth, ANOMALY_GROWTH = 0.20
    digest = build_digest(current, prior, {"data": []}, {}, window="7d")
    assert len(digest["anomalies"]) == 1
    a = digest["anomalies"][0]
    assert a["namespace"] == "production"
    assert a["growth_pct"] == 0.25
    assert a["current_cost_usd"] == 125.0
    assert a["prior_cost_usd"] == 100.0
    assert a["impact_usd"] == 25.0


def test_anomaly_below_threshold_not_flagged() -> None:
    current = _allocation_for("production", 110.0)
    prior = _allocation_for("production", 100.0)  # +10% growth, below threshold
    digest = build_digest(current, prior, {"data": []}, {}, window="7d")
    assert digest["anomalies"] == []


def test_anomaly_skipped_when_no_prior_baseline() -> None:
    current = _allocation_for("production", 100.0)
    digest = build_digest(current, None, {"data": []}, {}, window="7d")
    assert digest["anomalies"] == []


def test_anomaly_skipped_when_prior_was_zero() -> None:
    current = _allocation_for("brand-new-namespace", 100.0)
    prior = {"data": [{}]}  # No prior workloads at all.
    digest = build_digest(current, prior, {"data": []}, {}, window="7d")
    assert digest["anomalies"] == []


# -- PVC waste ---------------------------------------------------------------


def test_pvc_waste_flags_overprovisioned_disk() -> None:
    assets = {
        "data": [
            {
                "Disk/eks-prod-pv-bloated": {
                    "type": "Disk",
                    "totalCost": 25.0,
                    "bytesProvisioned": 100_000_000_000,
                    "bytesUsed": 10_000_000_000,
                }
            }
        ]
    }
    digest = build_digest({"data": []}, None, assets, {}, window="7d")
    assert len(digest["pvc_waste"]) == 1
    waste = digest["pvc_waste"][0]
    assert waste["name"] == "Disk/eks-prod-pv-bloated"
    assert waste["utilization"] == 0.1
    assert waste["impact_usd"] == 22.5


def test_pvc_waste_skips_well_utilized_disk() -> None:
    assets = {
        "data": [
            {
                "Disk/healthy": {
                    "type": "Disk",
                    "totalCost": 30.0,
                    "bytesProvisioned": 100_000_000_000,
                    "bytesUsed": 80_000_000_000,
                }
            }
        ]
    }
    digest = build_digest({"data": []}, None, assets, {}, window="7d")
    assert digest["pvc_waste"] == []


def test_pvc_waste_skips_low_cost_disk() -> None:
    assets = {
        "data": [
            {
                "Disk/cheap": {
                    "type": "Disk",
                    "totalCost": 2.0,
                    "bytesProvisioned": 100_000_000_000,
                    "bytesUsed": 1_000_000_000,
                }
            }
        ]
    }
    digest = build_digest({"data": []}, None, assets, {}, window="7d")
    assert digest["pvc_waste"] == []


def test_pvc_waste_skips_disks_without_byte_metrics() -> None:
    assets = _load("kubecost_assets.json")  # No bytesProvisioned/bytesUsed.
    digest = build_digest({"data": []}, None, assets, {}, window="7d")
    assert digest["pvc_waste"] == []


# -- Top namespaces & savings ------------------------------------------------


def test_top_namespaces_sorted_descending_with_share() -> None:
    allocation = _load("kubecost_allocation_accumulated.json")
    digest = build_digest(allocation, None, _load("kubecost_assets.json"), {}, window="7d")
    rows = digest["top_namespaces_by_cost"]
    assert rows[0]["namespace"] == "production"
    assert rows == sorted(rows, key=lambda r: -float(r["cost_usd"]))
    total_cost = digest["total_cost_usd"]
    assert all(0 <= r["share"] <= 1 for r in rows)
    assert sum(r["cost_usd"] for r in rows) <= total_cost + 0.01


def test_savings_signals_compacted_from_three_endpoints() -> None:
    allocation = _load("kubecost_allocation_accumulated.json")
    digest = build_digest(
        allocation, None, _load("kubecost_assets.json"), _savings_bundle(), window="7d"
    )
    s = digest["savings_signals"]
    assert s["request_sizing"]["candidate_count"] == 2
    assert s["request_sizing"]["total_monthly_savings_usd"] == 105.70
    assert s["cluster_sizing"]["recommended_nodes"] == 4
    assert s["abandoned_workloads"]["count"] == 2


def test_savings_signals_skips_missing_endpoints() -> None:
    digest = build_digest(
        {"data": []},
        None,
        {"data": []},
        {"request_sizing": None, "cluster_sizing": None, "abandoned_workloads": None},
        window="7d",
    )
    assert digest["savings_signals"] == {}


# -- Multi-bucket (accumulate=false) shape -----------------------------------


def test_build_digest_handles_bucketed_allocation_shape() -> None:
    allocation = _load("kubecost_allocation_buckets.json")
    digest = build_digest(allocation, None, {"data": []}, {}, window="7d")
    # Two buckets summed → api appears once, costs are bucket1+bucket2.
    api_cost_per_bucket = (
        # bucket 1
        6.02 + 1.36 + 0.0 + 0.0 + 0.46 + 2.57 + 0.16 + 0.0
    ) + (
        # bucket 2
        6.10 + 1.40 + 0.0 + 0.0 + 0.51 + 2.57 + 0.16 + 0.0
    )
    # Sentinels are excluded so only the api workload contributes.
    expected = round(api_cost_per_bucket, 2)
    actual = round(digest["total_cost_usd"] - digest["cluster_breakdown"]["idle_pool_cost_usd"], 2)
    assert actual == expected


# -- Size cap on 200-namespace fixture ---------------------------------------


def test_large_fixture_digest_under_size_cap() -> None:
    allocation = _load("kubecost_allocation_large.json")
    digest = build_digest(allocation, None, {"data": []}, {}, window="7d")
    size = _digest_size(digest)
    assert size <= DIGEST_MAX_BYTES, f"{size} > {DIGEST_MAX_BYTES}"
    assert digest["truncated"] is True
    assert digest["truncated_counts"]
    # At least one of the truncatable lists was capped.
    assert any(
        digest["truncated_counts"].get(k, 0) > 10
        for k in ("idle_workloads", "over_provisioned", "pvc_waste", "anomalies")
    )


def test_large_fixture_truncatable_lists_capped_at_top_n() -> None:
    allocation = _load("kubecost_allocation_large.json")
    digest = build_digest(allocation, None, {"data": []}, {}, window="7d")
    assert len(digest["idle_workloads"]) <= 10
    assert len(digest["over_provisioned"]) <= 10
    assert len(digest["pvc_waste"]) <= 10
    assert len(digest["anomalies"]) <= 10


# -- Rounding ---------------------------------------------------------------


def test_usd_fields_rounded_to_two_decimals_and_ratios_to_three() -> None:
    allocation = _load("kubecost_allocation_accumulated.json")
    digest = build_digest(
        allocation, None, _load("kubecost_assets.json"), _savings_bundle(), window="7d"
    )

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, float):
                    if k.endswith("_usd"):
                        assert round(v, 2) == v, f"{k}={v} not 2dp"
                    elif k in {
                        "share",
                        "growth_pct",
                        "cpu",
                        "memory",
                        "overall",
                        "cpu_util",
                        "mem_util",
                        "utilization",
                    }:
                        assert round(v, 3) == v, f"{k}={v} not 3dp"
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(digest)


# -- Size-cap phase coverage -------------------------------------------------


def _stuff(name: str, impact: float) -> dict[str, Any]:
    return {
        "name": name,
        "namespace": "stuffing",
        "controller_kind": "Deployment",
        "controller": name,
        "cpu_util": 0.05,
        "mem_util": 0.05,
        "cost_usd": impact,
        "impact_usd": impact,
    }


def test_size_cap_phase2_drops_low_impact_entries() -> None:
    # 10 high-impact + 10 low-impact entries per category, name-padded so that
    # phase 1 alone leaves the digest above the cap.
    digest: dict[str, Any] = {
        "window": "7d",
        "total_cost_usd": 0.0,
        "cluster_efficiency": {"cpu": 0.0, "memory": 0.0, "overall": 0.0},
        "cluster_breakdown": {
            "idle_pool_cost_usd": 0.0,
            "unallocated_cost_usd": 0.0,
            "unmounted_cost_usd": 0.0,
        },
        "top_namespaces_by_cost": [],
        "idle_workloads": [_stuff(f"idle-{'x' * 80}-{i}", 100.0) for i in range(10)]
        + [_stuff(f"low-impact-{'y' * 80}-{i}", 1.0) for i in range(10)],
        "over_provisioned": [_stuff(f"over-{'x' * 80}-{i}", 100.0) for i in range(10)]
        + [_stuff(f"low-impact-{'y' * 80}-{i}", 1.0) for i in range(10)],
        "pvc_waste": [_stuff(f"pvc-{'x' * 80}-{i}", 100.0) for i in range(10)]
        + [_stuff(f"low-impact-{'y' * 80}-{i}", 1.0) for i in range(10)],
        "anomalies": [_stuff(f"ano-{'x' * 80}-{i}", 100.0) for i in range(10)]
        + [_stuff(f"low-impact-{'y' * 80}-{i}", 1.0) for i in range(10)],
        "savings_signals": {},
        "truncated": False,
        "truncated_counts": {},
    }
    capped = pp._enforce_size_cap(digest)
    # Phase 1 caps each at 10. Then Phase 2 drops the low-impact entries.
    # Result: every kept item has impact >= LOW_IMPACT_USD.
    for key in ("idle_workloads", "over_provisioned", "pvc_waste", "anomalies"):
        impacts = [r["impact_usd"] for r in capped[key]]
        assert all(i >= 5.0 for i in impacts)
    assert capped["truncated"] is True
    assert capped["truncated_counts"]


def test_size_cap_phase3_shortens_long_names() -> None:
    long_name = "x" * 200
    digest: dict[str, Any] = {
        "window": "7d",
        "total_cost_usd": 0.0,
        "cluster_efficiency": {"cpu": 0.0, "memory": 0.0, "overall": 0.0},
        "cluster_breakdown": {
            "idle_pool_cost_usd": 0.0,
            "unallocated_cost_usd": 0.0,
            "unmounted_cost_usd": 0.0,
        },
        "top_namespaces_by_cost": [],
        # Each list has 10 entries with very long names AND high impact
        # (so phase 2 can't drop them). Phase 3 shortens names.
        "idle_workloads": [_stuff(f"{long_name}-{i}", 100.0) for i in range(10)],
        "over_provisioned": [_stuff(f"{long_name}-{i}", 100.0) for i in range(10)],
        "pvc_waste": [_stuff(f"{long_name}-{i}", 100.0) for i in range(10)],
        "anomalies": [_stuff(f"{long_name}-{i}", 100.0) for i in range(10)],
        "savings_signals": {},
        "truncated": False,
        "truncated_counts": {},
    }
    capped = pp._enforce_size_cap(digest)
    for key in ("idle_workloads", "over_provisioned", "pvc_waste", "anomalies"):
        for r in capped[key]:
            # Either name is short enough OR was truncated with the ellipsis.
            assert len(r["name"]) <= 60 or r["name"].endswith("…")


def test_size_cap_noop_when_under_threshold() -> None:
    digest = {
        "window": "7d",
        "total_cost_usd": 1.0,
        "cluster_efficiency": {"cpu": 0.0, "memory": 0.0, "overall": 0.0},
        "cluster_breakdown": {
            "idle_pool_cost_usd": 0.0,
            "unallocated_cost_usd": 0.0,
            "unmounted_cost_usd": 0.0,
        },
        "top_namespaces_by_cost": [],
        "idle_workloads": [],
        "over_provisioned": [],
        "pvc_waste": [],
        "anomalies": [],
        "savings_signals": {},
        "truncated": False,
        "truncated_counts": {},
    }
    capped = pp._enforce_size_cap(digest)
    assert capped["truncated"] is False
    assert capped["truncated_counts"] == {}
