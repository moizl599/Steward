"""Resolve digest_reference pointers into structured Finding fields.

The LLM produces findings with a digest_reference like
``"idle_workloads/default/deployment/nginx"``. The enricher looks up that
entry in the digest and copies the canonical ``impact_usd`` and
``affected_resource`` into the finding. This removes a category of model
failure — the model is unreliable at mechanical field copying but reliable
at choosing which findings to emit.

If a digest_reference is malformed or doesn't resolve, the finding is left
as-is (``impact_usd`` / ``affected_resource`` may be null). The validator
catches those cases downstream.
"""

from __future__ import annotations

from typing import Any

from app.schemas.report import Finding

_DIGEST_CATEGORIES: frozenset[str] = frozenset(
    {
        "idle_workloads",
        "over_provisioned",
        "pvc_waste",
        "anomalies",
    }
)


def enrich_findings(findings: list[Finding], digest: dict[str, Any]) -> list[Finding]:
    """Return a new list with ``impact_usd`` / ``affected_resource`` backfilled
    from the digest where each finding's ``digest_reference`` points.

    Pure function — does not mutate input. Findings without a usable
    ``digest_reference`` pass through unchanged.
    """
    return [_enrich_one(finding, digest) for finding in findings]


def _enrich_one(finding: Finding, digest: dict[str, Any]) -> Finding:
    ref = (finding.digest_reference or "").strip()
    if not ref:
        return finding

    category, _, name = ref.partition("/")
    if category not in _DIGEST_CATEGORIES or not name:
        # Malformed reference. Leave the finding alone; the validator
        # will surface this as a structured-field violation if needed.
        return finding

    entries = digest.get(category) or []
    # Anomalies use namespace as identity; the other three use the full
    # workload/PVC name.
    name_field = "namespace" if category == "anomalies" else "name"
    matched = next((e for e in entries if e.get(name_field) == name), None)
    if matched is None:
        return finding

    # Only backfill — don't overwrite values the model already set. This
    # matters when the model has good reason to override the digest (e.g.
    # cluster-wide cost attribution).
    impact = finding.impact_usd if finding.impact_usd is not None else matched.get("impact_usd")
    resource = finding.affected_resource if (finding.affected_resource or "").strip() else name
    return finding.model_copy(
        update={
            "impact_usd": impact,
            "affected_resource": resource,
        }
    )
