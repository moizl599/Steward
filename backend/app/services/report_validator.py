"""Post-LLM consistency check.

The LLM can produce structurally valid JSON that still contradicts the
digest (e.g. "no idle workloads" when the digest has four). This module
runs a small set of deterministic checks comparing the model's prose and
findings against the digest's ``analysis_hints``.

Failures are returned as a list of human-readable messages. The worker
feeds them back to the model in a single repair attempt; if the model
still fails, the worker logs the violations and proceeds with a banner
in the executive summary so the user knows the analysis disagreed with
its own data.

This is a string-and-counts check, not a semantic check. Keep it cheap.
"""

from __future__ import annotations

import re
from typing import Any

from app.schemas import ReportContent

# Phrases that imply "zero of X". We match conservatively; false positives
# here cost the model one repair attempt, false negatives let a bad report
# through.
_NEGATION_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "idle_workload_count": (
        re.compile(r"\bno\s+idle\s+workloads?\b", re.IGNORECASE),
        re.compile(r"\bzero\s+idle\s+workloads?\b", re.IGNORECASE),
        re.compile(r"\bno\s+workloads?\s+(are\s+)?idle\b", re.IGNORECASE),
        re.compile(r"\bthere\s+are\s+no\s+idle\b", re.IGNORECASE),
    ),
    "over_provisioned_count": (
        re.compile(r"\bno\s+over[- ]?provisioned\b", re.IGNORECASE),
        re.compile(r"\bno\s+over[- ]?provisioning\b", re.IGNORECASE),
        re.compile(r"\bnothing\s+is\s+over[- ]?provisioned\b", re.IGNORECASE),
    ),
    "pvc_waste_count": (
        re.compile(r"\bno\s+pvc\s+waste\b", re.IGNORECASE),
        re.compile(r"\bno\s+wasted\s+pvcs?\b", re.IGNORECASE),
    ),
    "anomaly_count": (re.compile(r"\bno\s+anomal(?:y|ies)\b", re.IGNORECASE),),
}

# Phrases that downplay a non-healthy grade. The grade is the digest's word;
# the LLM must not call a `poor` cluster "healthy".
_HEALTHY_DOWNPLAY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bcluster\s+(currently\s+|now\s+)?looks?\s+healthy\b", re.IGNORECASE),
    re.compile(r"\bwithin\s+a\s+reasonable\s+range\b", re.IGNORECASE),
    re.compile(r"\befficiency\s+is\s+(reasonable|healthy|good|fine)\b", re.IGNORECASE),
)

# Recommendation strings that are pure boilerplate. The prompt forbids these
# patterns; this catches the ones we've seen the model produce in practice.
_BOILERPLATE_RECOMMENDATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^\s*review\s+the\s+[`'\"]?[\w.-]+[`'\"]?\s+namespace\s+to\s+ensure\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*consider\s+adjusting\s+resource\s+requests?\s+and\s+limits?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*optimize\s+(the\s+)?[`'\"]?[\w.-]+[`'\"]?\s+namespace\s+costs?\.?\s*$",
        re.IGNORECASE,
    ),
)

# A namespace/kind/name workload reference, optionally backtick-quoted.
# Examples: default/deployment/nginx, `kubecost/StatefulSet/postgres`.
_WORKLOAD_REFERENCE_PATTERN: re.Pattern[str] = re.compile(r"`?[\w.-]+/[\w.-]+/[\w.-]+`?")

# Severities that require a dollar impact per the prompt's severity scale.
_DOLLAR_REQUIRED_SEVERITIES: frozenset[str] = frozenset({"critical", "high", "medium", "low"})

# Severity ceiling for trivial-scale clusters. The prompt's scale rules say
# trivial clusters are structural-health-only — the dollar bands that drive
# medium/high/critical aren't meaningful at < $50/mo run-rate.
_TRIVIAL_MAX_SEVERITIES: frozenset[str] = frozenset({"info", "low"})

# Digest categories that ``digest_reference`` can point at. Mirror of the
# resolver in ``finding_enricher`` — keep these in sync.
_DIGEST_REFERENCE_CATEGORIES: frozenset[str] = frozenset(
    {"idle_workloads", "over_provisioned", "pvc_waste", "anomalies"}
)


def validate_report(report: ReportContent, digest: dict[str, Any]) -> list[str]:
    """Return a list of contradictions between ``report`` and ``digest``.

    Empty list ⇒ the report is consistent with the digest. A non-empty list
    is suitable for inclusion in a repair prompt — each entry is a single
    declarative sentence the model can act on.
    """
    hints = digest.get("analysis_hints") or {}
    violations: list[str] = []

    summary = (report.executive_summary or "").strip()

    # 1. Negation contradictions ("no idle workloads" while count > 0).
    for hint_key, patterns in _NEGATION_PATTERNS.items():
        count = int(hints.get(hint_key) or 0)
        if count <= 0:
            continue
        for pattern in patterns:
            if pattern.search(summary):
                violations.append(
                    f"executive_summary states there are none, but "
                    f"analysis_hints.{hint_key} is {count}."
                )
                break  # one violation per hint is enough.

    # 2. Healthy-downplay when the grade says otherwise.
    grade = hints.get("efficiency_grade") or _efficiency_grade_from_digest(digest)
    if grade in {"poor", "critical", "mediocre"}:
        for pattern in _HEALTHY_DOWNPLAY_PATTERNS:
            if pattern.search(summary):
                violations.append(
                    f"executive_summary downplays efficiency, but "
                    f"analysis_hints.efficiency_grade is '{grade}'. Use the grade name."
                )
                break

    # 3. Boilerplate recommendations. Each violation names the finding index
    # so the repair prompt is unambiguous.
    for i, finding in enumerate(report.findings):
        rec = (finding.recommendation or "").strip()
        if not rec:
            violations.append(f"findings[{i}].recommendation is empty.")
            continue
        for pattern in _BOILERPLATE_RECOMMENDATION_PATTERNS:
            if pattern.search(rec):
                violations.append(
                    f"findings[{i}].recommendation is boilerplate "
                    f"({rec[:80]!r}). Name a specific workload, namespace, or "
                    f"controller from the digest."
                )
                break

        # 5. Trivial-scale severity ceiling. Placed BEFORE the impact_usd
        # check so the repair message guides the model to downgrade rather
        # than invent a dollar figure to satisfy a severity it shouldn't
        # have used in the first place.
        if (
            hints.get("cluster_scale") == "trivial"
            and finding.severity not in _TRIVIAL_MAX_SEVERITIES
        ):
            violations.append(
                f"findings[{i}].severity is '{finding.severity}' but "
                f"cluster_scale is 'trivial'. On trivial-scale clusters the "
                f"maximum severity is 'low'. Downgrade this finding to 'info' "
                f"(or 'low' if the issue genuinely warrants attention). Do "
                f"not try to satisfy the impact_usd rule by inventing a "
                f"dollar figure — the right fix is the downgrade."
            )

        # The model can defer mechanical field copying to the worker by
        # setting ``digest_reference``. Rules 6 and 7 exempt findings that do
        # so — the worker will populate impact_usd / affected_resource from
        # the digest before persistence. Rule 8 below then guarantees the
        # pointer actually resolves so the exemption isn't an escape hatch.
        has_digest_reference = bool((finding.digest_reference or "").strip())

        # 6. Required impact_usd for dollar-band severities. The severity
        # scale is defined in dollars, so e.g. ``high`` + ``impact_usd=None``
        # is internally contradictory.
        if (
            finding.severity in _DOLLAR_REQUIRED_SEVERITIES
            and finding.impact_usd is None
            and not has_digest_reference
        ):
            violations.append(
                f"findings[{i}].impact_usd is null but severity is "
                f"'{finding.severity}'. The severity bands are defined in "
                f"dollars; set impact_usd to the estimated monthly impact "
                f"in USD (or set digest_reference to point at the matching "
                f"digest entry)."
            )

        # 7. Required affected_resource when recommendation names a workload.
        # Keeps the structured field in sync with what the prose says, so the
        # frontend can render a badge instead of re-parsing the recommendation.
        if (
            _WORKLOAD_REFERENCE_PATTERN.search(rec)
            and not (finding.affected_resource or "").strip()
            and not has_digest_reference
        ):
            violations.append(
                f"findings[{i}].recommendation names a specific workload "
                f"but findings[{i}].affected_resource is empty. Populate "
                f"affected_resource with the workload identifier (e.g. "
                f"'namespace/kind/name') or set digest_reference to point "
                f"at the matching digest entry."
            )

        # 8. digest_reference must parse and resolve. Without this check the
        # exemption above is an escape hatch — the model could set
        # ``digest_reference`` to any garbage string to skip rules 6/7.
        if has_digest_reference:
            ref = (finding.digest_reference or "").strip()
            resolution_error = _digest_reference_resolution_error(ref, digest)
            if resolution_error is not None:
                violations.append(
                    f"findings[{i}].digest_reference is {ref!r} but "
                    f"{resolution_error}. Use the format "
                    f"'{{category}}/{{entry_name}}' where category is one "
                    f"of idle_workloads, over_provisioned, pvc_waste, "
                    f"anomalies, and entry_name matches a digest entry's "
                    f"name (or namespace for anomalies). Set to null for "
                    f"cluster-wide findings."
                )

    # 4. Trivial-cluster sanity. The prompt requires summary to acknowledge
    # the scale by name when scale is trivial.
    if hints.get("cluster_scale") == "trivial" and "trivial" not in summary.lower():
        violations.append(
            "cluster_scale is 'trivial' but executive_summary does not "
            "name the scale. State this up front so the reader doesn't "
            "treat dollar figures as production-meaningful."
        )

    # 5. Trivial-cluster savings field must be null or zero. The prompt
    # promises this; the LLM sometimes returns a small positive number
    # anyway (e.g. $0.63 on a $1.47/24h cluster). That false-precision
    # erodes trust on the FE.
    if hints.get("cluster_scale") == "trivial" and report.estimated_monthly_savings_usd not in (
        None,
        0,
        0.0,
    ):
        violations.append(
            f"cluster_scale is 'trivial' but estimated_monthly_savings_usd is "
            f"{report.estimated_monthly_savings_usd}. Set it to null or 0 — "
            f"dollar savings on a trivial-scale cluster are not meaningful."
        )

    return violations


def _digest_reference_resolution_error(ref: str, digest: dict[str, Any]) -> str | None:
    """Return a human-readable error if ``ref`` doesn't resolve, else None.

    Mirrors the parser in ``finding_enricher`` so any reference the validator
    accepts is also one the worker can backfill from.
    """
    category, sep, name = ref.partition("/")
    if not sep or not name:
        return "it is malformed (expected 'category/entry_name')"
    if category not in _DIGEST_REFERENCE_CATEGORIES:
        return (
            f"category '{category}' is unknown "
            f"(expected one of: {', '.join(sorted(_DIGEST_REFERENCE_CATEGORIES))})"
        )
    entries = digest.get(category) or []
    name_field = "namespace" if category == "anomalies" else "name"
    if not any(entry.get(name_field) == name for entry in entries):
        return f"no entry with {name_field}={name!r} exists in digest[{category!r}]"
    return None


def _efficiency_grade_from_digest(digest: dict[str, Any]) -> str | None:
    """Fallback when analysis_hints is missing (older digests)."""
    eff = digest.get("cluster_efficiency") or {}
    overall = eff.get("overall")
    if overall is None:
        return None
    if overall >= 0.50:
        return "healthy"
    if overall >= 0.30:
        return "mediocre"
    if overall >= 0.15:
        return "poor"
    return "critical"


def format_violations_for_prompt(violations: list[str]) -> str:
    """Render a numbered list of violations for the repair message."""
    return "\n".join(f"{i + 1}. {v}" for i, v in enumerate(violations))
