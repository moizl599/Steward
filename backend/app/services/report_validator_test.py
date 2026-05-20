"""Tests for the post-LLM consistency validator."""

from __future__ import annotations

from typing import Any

from app.schemas import ReportContent
from app.schemas.report import Finding
from app.services.report_validator import (
    format_violations_for_prompt,
    validate_report,
)


def _digest_with(
    *,
    idle: int = 0,
    over: int = 0,
    pvc: int = 0,
    anomalies: int = 0,
    grade: str = "healthy",
    scale: str = "production",
) -> dict[str, Any]:
    return {
        "analysis_hints": {
            "idle_workload_count": idle,
            "over_provisioned_count": over,
            "pvc_waste_count": pvc,
            "anomaly_count": anomalies,
            "efficiency_grade": grade,
            "cluster_scale": scale,
        },
        "cluster_efficiency": {"overall": 0.5},
    }


def _report(summary: str, findings: list[Finding] | None = None) -> ReportContent:
    return ReportContent(
        executive_summary=summary,
        findings=findings or [],
        estimated_monthly_savings_usd=None,
    )


def _finding(rec: str, *, severity: str = "info", title: str = "x") -> Finding:
    return Finding(
        title=title,
        severity=severity,  # type: ignore[arg-type]
        category="over_provisioning",  # type: ignore[arg-type]
        recommendation=rec,
    )


# -- Negation contradictions --------------------------------------------------


def test_flags_no_idle_workloads_when_count_positive() -> None:
    digest = _digest_with(idle=4, grade="critical", scale="trivial")
    report = _report(
        "This is a trivial-scale cluster. There are no idle workloads or "
        "over-provisioned resources. Efficiency is critical."
    )
    violations = validate_report(report, digest)
    assert any("idle_workload_count" in v for v in violations)


def test_passes_when_summary_acknowledges_idle_workloads() -> None:
    digest = _digest_with(idle=4, grade="critical", scale="trivial")
    report = _report(
        "This is a trivial-scale cluster with efficiency grade 'critical'. "
        "Four idle workloads were detected including nginx and redis."
    )
    violations = validate_report(report, digest)
    # No idle contradiction, no grade contradiction. Only check is the scale
    # name is mentioned ("trivial") — present here.
    assert not any("idle_workload_count" in v for v in violations)


def test_no_false_positive_when_count_is_zero() -> None:
    digest = _digest_with(idle=0, grade="healthy", scale="production")
    report = _report(
        "The cluster runs efficiently. There are no idle workloads or over-provisioned resources."
    )
    violations = validate_report(report, digest)
    assert violations == []


# -- Healthy-downplay ---------------------------------------------------------


def test_flags_downplay_when_grade_is_poor() -> None:
    digest = _digest_with(grade="poor", scale="small")
    report = _report(
        "This cluster currently looks healthy with efficiency within a reasonable range."
    )
    violations = validate_report(report, digest)
    assert any("downplay" in v for v in violations)


def test_no_downplay_flag_when_grade_is_healthy() -> None:
    digest = _digest_with(grade="healthy", scale="production")
    report = _report("This cluster currently looks healthy. Efficiency is healthy.")
    violations = validate_report(report, digest)
    assert not any("downplay" in v for v in violations)


# -- Boilerplate recommendations ---------------------------------------------


def test_flags_boilerplate_review_namespace_recommendation() -> None:
    digest = _digest_with(grade="healthy")
    report = _report(
        "Healthy cluster.",
        findings=[
            _finding(
                "Review the `kubecost` namespace to ensure that resources are "
                "being used efficiently."
            )
        ],
    )
    violations = validate_report(report, digest)
    assert any("boilerplate" in v for v in violations)


def test_flags_boilerplate_optimize_namespace_recommendation() -> None:
    digest = _digest_with(grade="healthy")
    report = _report(
        "Healthy cluster.",
        findings=[_finding("Optimize `default` namespace costs.")],
    )
    violations = validate_report(report, digest)
    assert any("boilerplate" in v for v in violations)


def test_does_not_flag_specific_recommendation() -> None:
    digest = _digest_with(grade="healthy")
    report = _report(
        "Healthy cluster.",
        findings=[
            _finding(
                "Delete the `data-science/Deployment/jupyter` deployment — "
                "idle at 4.5% CPU for the full window."
            )
        ],
    )
    violations = validate_report(report, digest)
    assert not any("boilerplate" in v for v in violations)


def test_flags_empty_recommendation() -> None:
    digest = _digest_with(grade="healthy")
    report = _report(
        "Healthy cluster.",
        findings=[_finding("   ")],  # whitespace only
    )
    violations = validate_report(report, digest)
    assert any("empty" in v for v in violations)


# -- Trivial-scale acknowledgement -------------------------------------------


def test_flags_trivial_cluster_without_scale_acknowledgement() -> None:
    digest = _digest_with(grade="critical", scale="trivial")
    report = _report("The cluster has critical efficiency at 8%. Idle workloads detected.")
    violations = validate_report(report, digest)
    assert any("'trivial'" in v for v in violations)


def test_passes_trivial_when_scale_named() -> None:
    digest = _digest_with(grade="critical", scale="trivial")
    report = _report(
        "This is a trivial-scale cluster with critical efficiency at 8%. "
        "Findings are about configuration health, not dollar impact."
    )
    violations = validate_report(report, digest)
    assert not any("'trivial'" in v for v in violations)


# -- Trivial-cluster savings enforcement -------------------------------------


def _report_with_savings(summary: str, savings: float | None) -> ReportContent:
    return ReportContent(
        executive_summary=summary,
        findings=[],
        estimated_monthly_savings_usd=savings,
    )


def test_flags_trivial_cluster_with_nonzero_savings() -> None:
    digest = _digest_with(grade="critical", scale="trivial")
    report = _report_with_savings(
        "This is a trivial-scale cluster with critical efficiency.",
        0.63,
    )
    violations = validate_report(report, digest)
    assert any("estimated_monthly_savings_usd" in v and "0.63" in v for v in violations)


def test_does_not_flag_trivial_cluster_with_null_savings() -> None:
    digest = _digest_with(grade="critical", scale="trivial")
    report = _report_with_savings(
        "This is a trivial-scale cluster with critical efficiency.",
        None,
    )
    violations = validate_report(report, digest)
    assert not any("estimated_monthly_savings_usd" in v for v in violations)


def test_does_not_flag_trivial_cluster_with_zero_savings() -> None:
    digest = _digest_with(grade="critical", scale="trivial")
    report = _report_with_savings(
        "This is a trivial-scale cluster with critical efficiency.",
        0.0,
    )
    violations = validate_report(report, digest)
    assert not any("estimated_monthly_savings_usd" in v for v in violations)


def test_does_not_flag_production_cluster_with_nonzero_savings() -> None:
    digest = _digest_with(grade="poor", scale="production")
    report = _report_with_savings(
        "Production cluster, efficiency grade is poor. Total identified "
        "savings of $1,240/mo across the findings list below.",
        1240.0,
    )
    violations = validate_report(report, digest)
    assert not any("estimated_monthly_savings_usd" in v for v in violations)


# -- impact_usd required for dollar-band severities --------------------------


def _finding_full(
    *,
    severity: str,
    recommendation: str,
    impact_usd: float | None = None,
    affected_resource: str | None = None,
    title: str = "f",
) -> Finding:
    return Finding(
        title=title,
        severity=severity,  # type: ignore[arg-type]
        category="over_provisioning",  # type: ignore[arg-type]
        recommendation=recommendation,
        impact_usd=impact_usd,
        affected_resource=affected_resource,
    )


def test_flags_critical_finding_with_null_impact_usd() -> None:
    digest = _digest_with(grade="poor", scale="production")
    report = _report(
        "Production cluster with poor efficiency.",
        findings=[
            _finding_full(
                severity="critical",
                recommendation="Delete the dead workload.",
                impact_usd=None,
            )
        ],
    )
    violations = validate_report(report, digest)
    assert any("impact_usd is null" in v and "'critical'" in v for v in violations)


def test_does_not_flag_critical_finding_with_populated_impact_usd() -> None:
    digest = _digest_with(grade="poor", scale="production")
    report = _report(
        "Production cluster with poor efficiency.",
        findings=[
            _finding_full(
                severity="critical",
                recommendation="Delete the dead workload.",
                impact_usd=250.0,
            )
        ],
    )
    violations = validate_report(report, digest)
    assert not any("impact_usd is null" in v for v in violations)


def test_does_not_flag_info_finding_with_null_impact_usd() -> None:
    digest = _digest_with(grade="healthy", scale="production")
    report = _report(
        "Healthy cluster.",
        findings=[
            _finding_full(
                severity="info",
                recommendation="No action required.",
                impact_usd=None,
            )
        ],
    )
    violations = validate_report(report, digest)
    assert not any("impact_usd is null" in v for v in violations)


# -- affected_resource required when recommendation names a workload --------


def test_flags_workload_in_recommendation_without_affected_resource() -> None:
    digest = _digest_with(grade="poor", scale="production")
    report = _report(
        "Production cluster with poor efficiency.",
        findings=[
            _finding_full(
                severity="low",
                recommendation=("Set CPU requests on `default/deployment/nginx` to ~50m."),
                impact_usd=40.0,
                affected_resource=None,
            )
        ],
    )
    violations = validate_report(report, digest)
    assert any("affected_resource is empty" in v for v in violations)


def test_does_not_flag_when_affected_resource_matches_workload() -> None:
    digest = _digest_with(grade="poor", scale="production")
    report = _report(
        "Production cluster with poor efficiency.",
        findings=[
            _finding_full(
                severity="low",
                recommendation=("Set CPU requests on `default/deployment/nginx` to ~50m."),
                impact_usd=40.0,
                affected_resource="default/deployment/nginx",
            )
        ],
    )
    violations = validate_report(report, digest)
    assert not any("affected_resource is empty" in v for v in violations)


def test_does_not_flag_namespace_only_reference() -> None:
    """A bare-namespace reference like ``kubecost`` shouldn't trip rule 6 —
    only slash-delimited workload references do."""
    digest = _digest_with(grade="poor", scale="production")
    report = _report(
        "Production cluster with poor efficiency.",
        findings=[
            _finding_full(
                severity="low",
                recommendation=("Look at the `kubecost` namespace; it dominates spend."),
                impact_usd=40.0,
                affected_resource=None,
            )
        ],
    )
    violations = validate_report(report, digest)
    assert not any("affected_resource is empty" in v for v in violations)


# -- Trivial-scale severity ceiling ------------------------------------------


def test_flags_trivial_cluster_with_high_severity() -> None:
    digest = _digest_with(grade="critical", scale="trivial")
    report = _report(
        "This is a trivial-scale cluster with critical efficiency.",
        findings=[
            _finding_full(
                severity="high",
                recommendation="Delete the `default/deployment/nginx` deployment.",
                impact_usd=12.0,
                affected_resource="default/deployment/nginx",
            )
        ],
    )
    violations = validate_report(report, digest)
    assert any("cluster_scale is 'trivial'" in v and "'high'" in v for v in violations)


def test_flags_trivial_cluster_with_medium_severity() -> None:
    digest = _digest_with(grade="poor", scale="trivial")
    report = _report(
        "This is a trivial-scale cluster.",
        findings=[
            _finding_full(
                severity="medium",
                recommendation="Tune `default/deployment/redis`.",
                impact_usd=8.0,
                affected_resource="default/deployment/redis",
            )
        ],
    )
    violations = validate_report(report, digest)
    assert any("'medium'" in v and "trivial" in v for v in violations)


def test_flags_trivial_cluster_with_critical_severity() -> None:
    digest = _digest_with(grade="critical", scale="trivial")
    report = _report(
        "This is a trivial-scale cluster.",
        findings=[
            _finding_full(
                severity="critical",
                recommendation="Address `default/deployment/nginx`.",
                impact_usd=20.0,
                affected_resource="default/deployment/nginx",
            )
        ],
    )
    violations = validate_report(report, digest)
    assert any("'critical'" in v and "trivial" in v for v in violations)


def test_does_not_flag_trivial_cluster_with_low_severity() -> None:
    digest = _digest_with(grade="poor", scale="trivial")
    report = _report(
        "This is a trivial-scale cluster.",
        findings=[
            _finding_full(
                severity="low",
                recommendation="Set CPU requests on `default/deployment/nginx`.",
                impact_usd=2.0,
                affected_resource="default/deployment/nginx",
            )
        ],
    )
    violations = validate_report(report, digest)
    assert not any("cluster_scale is 'trivial'" in v for v in violations)


def test_does_not_flag_trivial_cluster_with_info_severity() -> None:
    digest = _digest_with(grade="healthy", scale="trivial")
    report = _report(
        "This is a trivial-scale cluster that looks healthy.",
        findings=[
            _finding_full(
                severity="info",
                recommendation="No action needed; cluster is fine.",
            )
        ],
    )
    violations = validate_report(report, digest)
    assert not any("cluster_scale is 'trivial'" in v for v in violations)


def test_does_not_flag_small_cluster_with_high_severity() -> None:
    digest = _digest_with(grade="poor", scale="small")
    report = _report(
        "Small cluster with poor efficiency.",
        findings=[
            _finding_full(
                severity="high",
                recommendation="Trim `staging/deployment/api`.",
                impact_usd=420.0,
                affected_resource="staging/deployment/api",
            )
        ],
    )
    violations = validate_report(report, digest)
    assert not any("cluster_scale is 'trivial'" in v for v in violations)


def test_does_not_flag_production_cluster_with_critical_severity() -> None:
    digest = _digest_with(grade="critical", scale="production")
    report = _report(
        "Production cluster with critical efficiency.",
        findings=[
            _finding_full(
                severity="critical",
                recommendation="Replace `prod/deployment/api` provisioning.",
                impact_usd=5_400.0,
                affected_resource="prod/deployment/api",
            )
        ],
    )
    violations = validate_report(report, digest)
    assert not any("cluster_scale is 'trivial'" in v for v in violations)


def test_trivial_high_with_null_impact_emits_ceiling_violation_first() -> None:
    """Regression: when both the ceiling and the impact rule fire on the
    same finding, the ceiling violation must appear first so the repair
    prompt guides the model to downgrade rather than backfill a number."""
    digest = _digest_with(grade="critical", scale="trivial")
    report = _report(
        "This is a trivial-scale cluster with critical efficiency.",
        findings=[
            _finding_full(
                severity="high",
                recommendation="Delete the `default/deployment/redis` deployment.",
                impact_usd=None,
                affected_resource="default/deployment/redis",
            )
        ],
    )
    violations = validate_report(report, digest)

    # Both rules fire.
    ceiling_idx = next(i for i, v in enumerate(violations) if "cluster_scale is 'trivial'" in v)
    impact_idx = next(i for i, v in enumerate(violations) if "impact_usd is null" in v)
    # And the ceiling violation comes first in the list.
    assert ceiling_idx < impact_idx


def test_screenshot_scenario_v2_flags_both_new_rules() -> None:
    """Critical + null impact + null affected_resource + workload-in-prose —
    the model's preferred way to hide the structured fields."""
    digest = _digest_with(idle=2, grade="critical", scale="trivial")
    report = _report(
        "This is a trivial-scale cluster with critical efficiency.",
        findings=[
            _finding_full(
                severity="critical",
                recommendation=(
                    "Delete the `default/deployment/nginx` deployment — idle "
                    "for the full window at 0% CPU."
                ),
                impact_usd=None,
                affected_resource=None,
            )
        ],
    )
    violations = validate_report(report, digest)
    assert any("impact_usd is null" in v for v in violations)
    assert any("affected_resource is empty" in v for v in violations)


# -- digest_reference exemption (rules 6/7) and resolution check (rule 8) ----


def _digest_with_idle_entry(name: str = "default/Deployment/nginx") -> dict[str, Any]:
    """A digest with one idle workload entry suitable for digest_reference."""
    return {
        "analysis_hints": {
            "idle_workload_count": 1,
            "over_provisioned_count": 0,
            "pvc_waste_count": 0,
            "anomaly_count": 0,
            "efficiency_grade": "poor",
            "cluster_scale": "production",
        },
        "cluster_efficiency": {"overall": 0.3},
        "idle_workloads": [{"name": name, "namespace": name.split("/")[0], "impact_usd": 42.0}],
        "over_provisioned": [],
        "pvc_waste": [],
        "anomalies": [],
    }


def test_digest_reference_exempts_null_impact_for_dollar_severity() -> None:
    """Rule 6 must NOT fire when digest_reference is set — the worker fills
    impact_usd from the digest entry after analyze."""
    digest = _digest_with_idle_entry()
    report = _report(
        "Production cluster with poor efficiency.",
        findings=[
            Finding(
                title="Idle deployment",
                severity="low",
                category="idle_workloads",
                impact_usd=None,
                affected_resource=None,
                recommendation="Scale to zero outside business hours.",
                digest_reference="idle_workloads/default/Deployment/nginx",
            )
        ],
    )
    violations = validate_report(report, digest)
    assert not any("impact_usd is null" in v for v in violations)
    assert not any("affected_resource is empty" in v for v in violations)


def test_null_digest_reference_does_not_exempt_dollar_severity() -> None:
    """Without digest_reference, rule 6 still fires on null impact_usd."""
    digest = _digest_with_idle_entry()
    report = _report(
        "Production cluster with poor efficiency.",
        findings=[
            Finding(
                title="Idle deployment",
                severity="low",
                category="idle_workloads",
                impact_usd=None,
                affected_resource=None,
                recommendation="Scale to zero outside business hours.",
                digest_reference=None,
            )
        ],
    )
    violations = validate_report(report, digest)
    assert any("impact_usd is null" in v for v in violations)


def test_unresolvable_digest_reference_is_flagged() -> None:
    """Rule 8: a digest_reference pointing at a name that isn't in the
    digest must be flagged — otherwise the exemption is an escape hatch."""
    digest = _digest_with_idle_entry()
    report = _report(
        "Production cluster with poor efficiency.",
        findings=[
            Finding(
                title="Phantom workload",
                severity="low",
                category="idle_workloads",
                recommendation="Investigate.",
                digest_reference="idle_workloads/no-such-workload",
            )
        ],
    )
    violations = validate_report(report, digest)
    assert any("digest_reference" in v and "no entry" in v for v in violations)


def test_malformed_digest_reference_is_flagged() -> None:
    """Rule 8: a digest_reference with no slash is malformed."""
    digest = _digest_with_idle_entry()
    report = _report(
        "Production cluster with poor efficiency.",
        findings=[
            Finding(
                title="Bad pointer",
                severity="low",
                category="idle_workloads",
                recommendation="Investigate.",
                digest_reference="just-a-name",
            )
        ],
    )
    violations = validate_report(report, digest)
    assert any("digest_reference" in v and "malformed" in v for v in violations)


# -- Format helper ------------------------------------------------------------


def test_format_violations_numbers_each_entry() -> None:
    out = format_violations_for_prompt(["alpha violation.", "beta violation."])
    assert "1. alpha violation." in out
    assert "2. beta violation." in out


def test_format_empty_violations_returns_empty_string() -> None:
    assert format_violations_for_prompt([]) == ""


# -- Real-world regression ---------------------------------------------------


def test_screenshot_scenario_is_flagged() -> None:
    """The exact case from the user's screenshot must be caught.

    8% cluster efficiency on a $0.02/24h cluster, four idle workloads, and
    a summary that says "no idle workloads" and "within a reasonable range".
    """
    digest = _digest_with(idle=4, grade="critical", scale="trivial")
    report = _report(
        "This cluster currently looks healthy, with no significant cost-saving "
        "opportunities identified. The overall cluster efficiency is 8.3%, "
        "which is within a reasonable range, and there are no idle workloads "
        "or over-provisioned resources."
    )
    violations = validate_report(report, digest)
    # We expect at least: idle contradiction, healthy-downplay, trivial-scale
    # not named.
    assert len(violations) >= 3
    assert any("idle_workload_count" in v for v in violations)
    assert any("downplay" in v for v in violations)
    assert any("'trivial'" in v for v in violations)
