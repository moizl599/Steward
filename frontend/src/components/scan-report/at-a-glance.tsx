"use client";

import type { ClusterScale, Digest, EfficiencyGrade } from "@/lib/digest";
import { gradeFromRatio } from "@/lib/digest";
import { cn, formatUSD } from "@/lib/utils";

interface AtAGlanceProps {
  digest: Digest;
}

/**
 * Three-card glance strip: scale + run-rate, three efficiency dials,
 * and the four analysis-hint counts. Every value is sourced from the
 * digest — no scenario-specific hardcoding.
 */
export function AtAGlance({ digest }: AtAGlanceProps) {
  return (
    <section className="mt-8 grid gap-3 md:grid-cols-[1fr_1.4fr_1fr]">
      <ScaleCard digest={digest} />
      <EfficiencyCard digest={digest} />
      <SignalCountsCard digest={digest} />
    </section>
  );
}

// -- ScalePill (also used by ScanHeader) -------------------------------------

const SCALE_PILL_STYLES: Record<ClusterScale, string> = {
  trivial:
    "border-[var(--color-destructive)]/40 bg-[var(--color-destructive)]/15 text-[var(--color-destructive)]",
  small: "border-[var(--color-border)] bg-[var(--color-muted)] text-[var(--color-foreground)]",
  production:
    "border-[var(--color-savings)]/40 bg-[var(--color-savings)]/10 text-[var(--color-savings)]",
};

const SCALE_LABEL: Record<ClusterScale, string> = {
  trivial: "Trivial",
  small: "Small",
  production: "Production",
};

export function ScalePill({
  scale,
  className,
}: {
  scale: ClusterScale;
  className?: string;
}) {
  return (
    <span
      data-scale={scale}
      className={cn(
        "inline-flex items-center rounded border px-2 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wider",
        SCALE_PILL_STYLES[scale],
        className,
      )}
    >
      {SCALE_LABEL[scale]}
    </span>
  );
}

// -- ScaleCard ---------------------------------------------------------------

const SCALE_SUBLABEL: Record<ClusterScale, string> = {
  trivial: "lab / dev cluster",
  small: "small workload",
  production: "production workload",
};

function ScaleCard({ digest }: { digest: Digest }) {
  const scale = digest.cluster_scale;
  return (
    <article className="flex flex-col rounded-md border border-[var(--color-border)] bg-[var(--color-card)] p-4">
      <Eyebrow>Cluster scale</Eyebrow>
      <div className="mt-2 flex items-center gap-2">
        <h3 className="font-display text-2xl font-bold tracking-tight">
          {SCALE_LABEL[scale]}
        </h3>
        <ScalePill scale={scale} />
      </div>
      <p className="mt-1 text-xs text-[var(--color-muted-foreground)]">
        {SCALE_SUBLABEL[scale]}
      </p>
      <div className="mt-auto flex items-baseline justify-between border-t border-[var(--color-border)] pt-3">
        <span className="font-mono text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
          Run-rate
        </span>
        <span className="font-mono text-sm font-semibold tabular-nums">
          {formatUSD(digest.monthly_run_rate_usd)}{" "}
          <span className="text-[var(--color-muted-foreground)] font-normal">/ mo</span>
        </span>
      </div>
    </article>
  );
}

// -- EfficiencyCard ----------------------------------------------------------

const GRADE_LABEL: Record<EfficiencyGrade, string> = {
  healthy: "Healthy",
  mediocre: "Mediocre",
  poor: "Poor",
  critical: "Critical",
};

const GRADE_CHIP_STYLES: Record<EfficiencyGrade, string> = {
  healthy:
    "border-[var(--color-savings)]/40 bg-[var(--color-savings)]/10 text-[var(--color-savings)]",
  mediocre:
    "border-[var(--color-warn)]/40 bg-[var(--color-warn)]/10 text-[var(--color-warn)]",
  poor:
    "border-[var(--color-destructive)]/40 bg-[var(--color-destructive)]/10 text-[var(--color-destructive)]",
  critical:
    "border-[var(--color-destructive)]/50 bg-[var(--color-destructive)]/15 text-[var(--color-destructive)]",
};

function gradeStroke(grade: EfficiencyGrade): { stroke: string; opacity: number } {
  switch (grade) {
    case "healthy":
      return { stroke: "var(--color-savings)", opacity: 1 };
    case "mediocre":
      return { stroke: "var(--color-warn)", opacity: 1 };
    case "poor":
      return { stroke: "var(--color-destructive)", opacity: 0.65 };
    case "critical":
      return { stroke: "var(--color-destructive)", opacity: 1 };
  }
}

function EfficiencyCard({ digest }: { digest: Digest }) {
  const { cpu, memory, overall } = digest.cluster_efficiency;
  const grade = digest.efficiency_grade;
  return (
    <article className="flex flex-col rounded-md border border-[var(--color-border)] bg-[var(--color-card)] p-4">
      <div className="flex items-center justify-between">
        <Eyebrow>Cluster efficiency</Eyebrow>
        <GradeChip grade={grade} />
      </div>
      <div className="mt-3 flex flex-1 items-center justify-around gap-2">
        <EfficiencyDial value={cpu} label="CPU" />
        <EfficiencyDial value={memory} label="Memory" />
        <EfficiencyDial value={overall} label="Overall" grade={grade} />
      </div>
    </article>
  );
}

export function GradeChip({
  grade,
  className,
}: {
  grade: EfficiencyGrade;
  className?: string;
}) {
  return (
    <span
      data-grade={grade}
      className={cn(
        "inline-flex items-center rounded border px-2 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wider",
        GRADE_CHIP_STYLES[grade],
        className,
      )}
    >
      {GRADE_LABEL[grade]}
    </span>
  );
}

/**
 * Per-resource arc dial. ``grade`` defaults to bucketing the ratio so each
 * dial colours independently — a 60% memory dial stays green even when the
 * overall grade is critical.
 */
export function EfficiencyDial({
  value,
  label,
  grade,
}: {
  value: number;
  label: string;
  grade?: EfficiencyGrade;
}) {
  const ratio = Math.max(0, Math.min(value, 1));
  const radius = 22;
  const circumference = 2 * Math.PI * radius;
  const dash = ratio * circumference;
  const effectiveGrade = grade ?? gradeFromRatio(value);
  const { stroke, opacity } = gradeStroke(effectiveGrade);
  return (
    <div className="flex flex-col items-center" data-testid={`dial-${label.toLowerCase()}`}>
      <svg
        viewBox="0 0 60 60"
        width={60}
        height={60}
        role="img"
        aria-label={`${label} efficiency ${(value * 100).toFixed(1)} percent`}
      >
        <circle
          cx={30}
          cy={30}
          r={radius}
          fill="none"
          stroke="var(--color-border)"
          strokeWidth={4}
        />
        <circle
          cx={30}
          cy={30}
          r={radius}
          fill="none"
          stroke={stroke}
          strokeOpacity={opacity}
          strokeWidth={4}
          strokeDasharray={`${dash} ${circumference}`}
          strokeLinecap="round"
          transform="rotate(-90 30 30)"
        />
        <text
          x={30}
          y={33}
          textAnchor="middle"
          fontSize={11}
          fontFamily="var(--font-mono)"
          fill="var(--color-foreground)"
          data-testid={`dial-${label.toLowerCase()}-value`}
        >
          {(value * 100).toFixed(1)}%
        </text>
      </svg>
      <p className="mt-1 font-mono text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
        {label}
      </p>
    </div>
  );
}

// -- SignalCountsCard --------------------------------------------------------

interface SignalCell {
  label: string;
  count: number;
  tone: "destructive" | "warn";
  href: string | null;
  testId: string;
}

function SignalCountsCard({ digest }: { digest: Digest }) {
  const hints = digest.analysis_hints;
  const cells: SignalCell[] = [
    {
      label: "Idle",
      count: hints.idle_workload_count,
      tone: "destructive",
      href: "#idle",
      testId: "signal-idle",
    },
    {
      label: "Over-prov",
      count: hints.over_provisioned_count,
      tone: "warn",
      href: "#over-prov",
      testId: "signal-overprov",
    },
    {
      label: "PVC waste",
      count: hints.pvc_waste_count,
      tone: "warn",
      href: "#pvc-waste",
      testId: "signal-pvc",
    },
    {
      label: "Anomalies",
      count: hints.anomaly_count,
      tone: "destructive",
      href: null, // No table yet; cell is non-interactive.
      testId: "signal-anomalies",
    },
  ];

  return (
    <article className="flex flex-col rounded-md border border-[var(--color-border)] bg-[var(--color-card)] p-4">
      <Eyebrow>Signals</Eyebrow>
      <div className="mt-3 grid flex-1 grid-cols-2 gap-2">
        {cells.map((cell) => (
          <SignalCellButton key={cell.label} cell={cell} />
        ))}
      </div>
    </article>
  );
}

function SignalCellButton({ cell }: { cell: SignalCell }) {
  const numberColour =
    cell.count <= 0
      ? "text-[var(--color-muted-foreground)]"
      : cell.tone === "destructive"
        ? "text-[var(--color-destructive)]"
        : "text-[var(--color-warn)]";

  const inner = (
    <>
      <span
        className={cn(
          "font-display text-2xl font-bold tabular-nums",
          numberColour,
        )}
      >
        {cell.count}
      </span>
      <span className="font-mono text-[9px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
        {cell.label}
      </span>
    </>
  );

  if (cell.href == null) {
    return (
      <div
        data-testid={cell.testId}
        data-interactive="false"
        className="flex flex-col items-start justify-between rounded border border-[var(--color-border)]/60 bg-[var(--color-background)]/40 p-2"
      >
        {inner}
      </div>
    );
  }

  return (
    <button
      type="button"
      data-testid={cell.testId}
      data-interactive="true"
      onClick={(e) => {
        e.preventDefault();
        const id = cell.href!.slice(1);
        const target = document.getElementById(id);
        target?.scrollIntoView({ behavior: "smooth", block: "start" });
      }}
      className="flex flex-col items-start justify-between rounded border border-[var(--color-border)] bg-[var(--color-background)]/60 p-2 text-left transition-colors hover:border-[var(--color-muted-foreground)]/40 hover:bg-[var(--color-accent)]"
    >
      {inner}
    </button>
  );
}

// -- Internals ---------------------------------------------------------------

function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <p className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-muted-foreground)]">
      {children}
    </p>
  );
}
