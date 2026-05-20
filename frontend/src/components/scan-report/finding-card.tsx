"use client";

import { useState } from "react";
import { CheckCircle2, ChevronDown, ChevronRight } from "lucide-react";

import { SeverityBadge } from "@/components/severity-badge";
import type { Finding } from "@/lib/api";
import { cn, formatUSD } from "@/lib/utils";

type LeftBorder = "destructive" | "warn-strong" | "warn" | "muted" | "none";

const LEFT_BORDER_BY_SEVERITY: Record<Finding["severity"], LeftBorder> = {
  critical: "destructive",
  high: "warn-strong",
  medium: "warn",
  low: "muted",
  info: "none",
};

const LEFT_BORDER_CLASS: Record<LeftBorder, string> = {
  destructive: "border-l-[3px] border-l-[var(--color-destructive)]",
  "warn-strong":
    "border-l-[3px] border-l-[var(--color-destructive)]/60",
  warn: "border-l-[3px] border-l-[var(--color-warn)]",
  muted: "border-l-[3px] border-l-[var(--color-muted-foreground)]",
  none: "",
};

const IMPACT_COLOUR_BY_SEVERITY: Record<Finding["severity"], string> = {
  critical: "text-[var(--color-destructive)]",
  high: "text-[var(--color-destructive)]/70",
  medium: "text-[var(--color-warn)]",
  low: "text-[var(--color-savings)]",
  info: "text-[var(--color-savings)]",
};

interface FindingCardProps {
  finding: Finding;
  /** Render the small "everything looks fine" variant. The page enables this
   * when there is exactly one info finding AND the cluster grade is healthy. */
  healthyVariant?: boolean;
}

export function FindingCard({ finding, healthyVariant }: FindingCardProps) {
  if (healthyVariant && finding.severity === "info") {
    return (
      <li
        data-testid="finding-row"
        data-variant="healthy"
        className="flex items-center gap-3 rounded-md border border-[var(--color-border)] bg-[var(--color-card)] px-5 py-3"
      >
        <CheckCircle2 className="size-4 text-[var(--color-savings)]" aria-hidden />
        <p className="text-sm text-[var(--color-muted-foreground)]">
          {finding.title}
        </p>
      </li>
    );
  }

  return <FullFindingCard finding={finding} />;
}

function FullFindingCard({ finding }: { finding: Finding }) {
  const [open, setOpen] = useState(false);
  const leftBorder = LEFT_BORDER_BY_SEVERITY[finding.severity];
  const impactColour = IMPACT_COLOUR_BY_SEVERITY[finding.severity];

  return (
    <li
      data-testid="finding-row"
      data-severity={finding.severity}
      className={cn(
        "rounded-md border border-[var(--color-border)] bg-[var(--color-card)] p-5",
        LEFT_BORDER_CLASS[leftBorder],
      )}
    >
      <div className="flex items-start gap-4">
        <SeverityBadge severity={finding.severity} className="mt-0.5" />
        <div className="min-w-0 flex-1">
          <h3 className="font-medium leading-snug">{finding.title}</h3>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
              {finding.category}
            </span>
            {finding.affected_resource ? (
              <>
                <span aria-hidden className="text-[var(--color-border)]">
                  ·
                </span>
                <span
                  data-testid="finding-affected-resource"
                  // Workload names are case-sensitive in K8s — render in
                  // original case (not uppercase), inside a small pill so
                  // it's visually a structured field, not appended prose.
                  className="rounded border border-[var(--color-border)] bg-[var(--color-background)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-foreground)]"
                  title={finding.affected_resource}
                >
                  {finding.affected_resource}
                </span>
              </>
            ) : null}
          </div>
        </div>
        {finding.impact_usd != null ? (
          <span
            className={cn(
              "shrink-0 font-mono text-sm font-semibold tabular-nums",
              impactColour,
            )}
            data-testid="finding-impact"
          >
            {formatUSD(finding.impact_usd)}{" "}
            <span className="font-normal text-[var(--color-muted-foreground)]">
              / mo
            </span>
          </span>
        ) : null}
      </div>
      <p className="mt-3 text-sm leading-relaxed text-[var(--color-foreground)]/90">
        {finding.recommendation}
      </p>
      {finding.rationale ? (
        <>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="mt-3 inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]"
            aria-expanded={open}
            data-testid="finding-rationale-toggle"
          >
            {open ? (
              <ChevronDown className="size-3" />
            ) : (
              <ChevronRight className="size-3" />
            )}
            Why this matters
          </button>
          {open ? (
            <p
              data-testid="finding-rationale"
              className="mt-2 border-l-2 border-[var(--color-border)] pl-3 text-xs leading-relaxed text-[var(--color-muted-foreground)]"
            >
              {finding.rationale}
            </p>
          ) : null}
        </>
      ) : null}
    </li>
  );
}

const SEVERITY_RANK: Record<Finding["severity"], number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4,
};

/** Sort findings by severity desc then impact desc. */
export function sortFindings(findings: Finding[]): Finding[] {
  return [...findings].sort((a, b) => {
    const sev = SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity];
    if (sev !== 0) return sev;
    return (b.impact_usd ?? 0) - (a.impact_usd ?? 0);
  });
}
