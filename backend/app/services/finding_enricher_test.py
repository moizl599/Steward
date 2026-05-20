"""Tests for the digest_reference → structured-field resolver."""

from __future__ import annotations

from typing import Any

from app.schemas.report import Finding
from app.services.finding_enricher import enrich_findings


def _finding(
    *,
    digest_reference: str | None = None,
    impact_usd: float | None = None,
    affected_resource: str | None = None,
    severity: str = "low",
    title: str = "f",
    recommendation: str = "do thing",
) -> Finding:
    return Finding(
        title=title,
        severity=severity,  # type: ignore[arg-type]
        category="idle_workloads",  # type: ignore[arg-type]
        impact_usd=impact_usd,
        affected_resource=affected_resource,
        recommendation=recommendation,
        digest_reference=digest_reference,
    )


def _digest_with_idle(name: str, impact: float) -> dict[str, Any]:
    return {
        "idle_workloads": [
            {
                "name": name,
                "namespace": "default",
                "impact_usd": impact,
                "cost_usd": impact,
                "cpu_util": 0.0,
                "mem_util": 0.0,
            }
        ],
        "over_provisioned": [],
        "pvc_waste": [],
        "anomalies": [],
    }


# -- Happy path -------------------------------------------------------------


def test_resolves_idle_workload_reference() -> None:
    digest = _digest_with_idle("default/deployment/nginx", 12.5)
    finding = _finding(digest_reference="idle_workloads/default/deployment/nginx")
    [out] = enrich_findings([finding], digest)
    assert out.impact_usd == 12.5
    assert out.affected_resource == "default/deployment/nginx"


def test_resolves_anomaly_by_namespace() -> None:
    digest: dict[str, Any] = {
        "idle_workloads": [],
        "over_provisioned": [],
        "pvc_waste": [],
        "anomalies": [
            {
                "namespace": "data-science",
                "current_cost_usd": 200.0,
                "prior_cost_usd": 150.0,
                "growth_pct": 0.333,
                "impact_usd": 50.0,
            }
        ],
    }
    finding = _finding(digest_reference="anomalies/data-science")
    [out] = enrich_findings([finding], digest)
    assert out.impact_usd == 50.0
    assert out.affected_resource == "data-science"


def test_resolves_over_provisioned_with_slashed_name() -> None:
    digest: dict[str, Any] = {
        "idle_workloads": [],
        "over_provisioned": [
            {
                "name": "production/StatefulSet/postgres",
                "namespace": "production",
                "impact_usd": 73.1,
            }
        ],
        "pvc_waste": [],
        "anomalies": [],
    }
    finding = _finding(digest_reference="over_provisioned/production/StatefulSet/postgres")
    [out] = enrich_findings([finding], digest)
    assert out.impact_usd == 73.1
    assert out.affected_resource == "production/StatefulSet/postgres"


# -- Pass-through cases -----------------------------------------------------


def test_passes_through_when_reference_is_null() -> None:
    digest = _digest_with_idle("default/deployment/nginx", 12.5)
    finding = _finding(digest_reference=None)
    [out] = enrich_findings([finding], digest)
    assert out.impact_usd is None
    assert out.affected_resource is None


def test_passes_through_when_reference_is_malformed_no_slash() -> None:
    digest = _digest_with_idle("default/deployment/nginx", 12.5)
    finding = _finding(digest_reference="just-a-name")
    [out] = enrich_findings([finding], digest)
    assert out.impact_usd is None
    assert out.affected_resource is None


def test_passes_through_when_category_is_unknown() -> None:
    digest = _digest_with_idle("default/deployment/nginx", 12.5)
    finding = _finding(digest_reference="something_else/default/deployment/nginx")
    [out] = enrich_findings([finding], digest)
    assert out.impact_usd is None
    assert out.affected_resource is None


def test_passes_through_when_name_not_found() -> None:
    digest = _digest_with_idle("default/deployment/nginx", 12.5)
    finding = _finding(digest_reference="idle_workloads/no-such-workload")
    [out] = enrich_findings([finding], digest)
    assert out.impact_usd is None
    assert out.affected_resource is None


# -- Non-overwrite guarantees -----------------------------------------------


def test_does_not_overwrite_non_null_impact_usd() -> None:
    digest = _digest_with_idle("default/deployment/nginx", 12.5)
    finding = _finding(
        digest_reference="idle_workloads/default/deployment/nginx",
        impact_usd=99.99,
    )
    [out] = enrich_findings([finding], digest)
    assert out.impact_usd == 99.99
    # Affected resource was unset → enricher fills from the entry name.
    assert out.affected_resource == "default/deployment/nginx"


def test_does_not_overwrite_non_empty_affected_resource() -> None:
    digest = _digest_with_idle("default/deployment/nginx", 12.5)
    finding = _finding(
        digest_reference="idle_workloads/default/deployment/nginx",
        affected_resource="custom-label",
    )
    [out] = enrich_findings([finding], digest)
    assert out.affected_resource == "custom-label"
    # Impact was unset → enricher fills from the digest entry.
    assert out.impact_usd == 12.5


# -- Purity -----------------------------------------------------------------


def test_enrich_findings_is_pure() -> None:
    digest = _digest_with_idle("default/deployment/nginx", 12.5)
    original = _finding(digest_reference="idle_workloads/default/deployment/nginx")
    [enriched] = enrich_findings([original], digest)
    # Original untouched.
    assert original.impact_usd is None
    assert original.affected_resource is None
    # Enriched copy populated.
    assert enriched.impact_usd == 12.5
    assert enriched is not original


def test_handles_empty_list() -> None:
    digest = _digest_with_idle("default/deployment/nginx", 12.5)
    assert enrich_findings([], digest) == []
