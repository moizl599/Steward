"use client";

import { type ReactNode } from "react";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { IdleWorkload, OverProvWorkload, PvcWaste } from "@/lib/digest";
import { cn, formatUSD } from "@/lib/utils";

// -- Section shell -----------------------------------------------------------

interface SectionShellProps {
  id: "idle" | "over-prov" | "pvc-waste";
  title: string;
  subtitle: string;
  isEmpty: boolean;
  emptyMessage: string;
  children: ReactNode;
}

function SectionShell({
  id,
  title,
  subtitle,
  isEmpty,
  emptyMessage,
  children,
}: SectionShellProps) {
  return (
    <section id={id} className="mt-8 scroll-mt-12" data-testid={`section-${id}`}>
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="font-display text-lg font-bold tracking-tight">{title}</h2>
        <p className="font-mono text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
          {subtitle}
        </p>
      </div>
      {isEmpty ? (
        <p
          data-testid={`section-${id}-empty`}
          className="mt-3 rounded border border-dashed border-[var(--color-border)] bg-[var(--color-card)]/40 px-4 py-3 text-sm text-[var(--color-muted-foreground)]"
        >
          {emptyMessage}
        </p>
      ) : (
        <div className="mt-3 overflow-hidden rounded-md border border-[var(--color-border)]">
          {children}
        </div>
      )}
    </section>
  );
}

// -- Inline bar (CPU/Mem/Util) ----------------------------------------------

function utilBarClass(value: number): string {
  if (value < 0.05) return "bg-[var(--color-destructive)]";
  if (value < 0.2) return "bg-[var(--color-warn)]";
  return "bg-[var(--color-muted-foreground)]";
}

export function UtilCell({
  value,
  testId,
}: {
  value: number;
  testId?: string;
}) {
  const display = Math.min(Math.max(value, 0), 1);
  return (
    <div className="flex items-center gap-2" data-testid={testId}>
      <div className="h-1 w-12 shrink-0 rounded-full bg-[var(--color-border)]">
        <div
          className={cn("h-1 rounded-full", utilBarClass(value))}
          style={{ width: `${display * 100}%` }}
        />
      </div>
      <span className="font-mono text-xs tabular-nums">
        {(value * 100).toFixed(1)}%
      </span>
    </div>
  );
}

// -- Bytes formatter ---------------------------------------------------------

export function formatBytes(bytes: number): string {
  if (bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let n = bytes;
  let unit = 0;
  while (n >= 1024 && unit < units.length - 1) {
    n /= 1024;
    unit++;
  }
  const decimals = n >= 100 || unit === 0 ? 0 : 1;
  return `${n.toFixed(decimals)} ${units[unit]}`;
}

// -- Workload name truncation -----------------------------------------------

const NAME_TRUNC_LEN = 40;
function truncName(name: string): string {
  return name.length <= NAME_TRUNC_LEN
    ? name
    : `${name.slice(0, NAME_TRUNC_LEN - 1)}…`;
}

// -- Impact cell -------------------------------------------------------------

function ImpactCell({ value }: { value: number | null | undefined }) {
  if (value == null || value <= 0) {
    return (
      <span className="font-mono text-xs tabular-nums text-[var(--color-muted-foreground)]">
        —
      </span>
    );
  }
  return (
    <span className="font-mono text-xs font-semibold tabular-nums text-[var(--color-savings)]">
      {formatUSD(value)}
      <span className="ml-0.5 font-normal text-[var(--color-muted-foreground)]">
        / mo
      </span>
    </span>
  );
}

// -- Sort helper -------------------------------------------------------------

function sortByImpactThenName<T extends { impact_usd: number; name: string }>(
  rows: T[],
): T[] {
  return [...rows].sort((a, b) => {
    if (b.impact_usd !== a.impact_usd) return b.impact_usd - a.impact_usd;
    return a.name.localeCompare(b.name);
  });
}

// -- IdleWorkloadsTable ------------------------------------------------------

export function IdleWorkloadsTable({ rows }: { rows: IdleWorkload[] }) {
  const sorted = sortByImpactThenName(rows);
  return (
    <SectionShell
      id="idle"
      title="Idle workloads"
      subtitle="CPU < 5% · Memory < 10%"
      isEmpty={sorted.length === 0}
      emptyMessage="No idle workloads in this scan."
    >
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Workload</TableHead>
            <TableHead>Namespace</TableHead>
            <TableHead>CPU util</TableHead>
            <TableHead>Mem util</TableHead>
            <TableHead className="text-right">Cost</TableHead>
            <TableHead className="text-right">Impact</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((row) => (
            <TableRow
              key={row.name}
              data-testid={`idle-row-${row.name}`}
              className="hover:bg-[var(--color-accent)]/40"
            >
              <TableCell
                className="font-mono text-xs"
                title={row.name}
              >
                {truncName(row.name)}
              </TableCell>
              <TableCell className="font-mono text-xs text-[var(--color-muted-foreground)]">
                {row.namespace ?? "—"}
              </TableCell>
              <TableCell>
                <UtilCell value={row.cpu_util} testId={`idle-cpu-${row.name}`} />
              </TableCell>
              <TableCell>
                <UtilCell value={row.mem_util} testId={`idle-mem-${row.name}`} />
              </TableCell>
              <TableCell className="text-right font-mono text-xs tabular-nums">
                {formatUSD(row.cost_usd)}
              </TableCell>
              <TableCell className="text-right">
                <ImpactCell value={row.impact_usd} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </SectionShell>
  );
}

// -- OverProvisionedTable ----------------------------------------------------

export function OverProvisionedTable({
  rows,
}: {
  rows: OverProvWorkload[];
}) {
  const sorted = sortByImpactThenName(rows);
  return (
    <SectionShell
      id="over-prov"
      title="Over-provisioned"
      subtitle="Request > 4× usage · cost > $20"
      isEmpty={sorted.length === 0}
      emptyMessage="No over-provisioned workloads in this scan."
    >
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Workload</TableHead>
            <TableHead>Namespace</TableHead>
            <TableHead>CPU util</TableHead>
            <TableHead>Mem util</TableHead>
            <TableHead className="text-right">Cost</TableHead>
            <TableHead className="text-right">Impact</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((row) => (
            <TableRow
              key={row.name}
              data-testid={`overprov-row-${row.name}`}
              className="hover:bg-[var(--color-accent)]/40"
            >
              <TableCell className="font-mono text-xs" title={row.name}>
                {truncName(row.name)}
              </TableCell>
              <TableCell className="font-mono text-xs text-[var(--color-muted-foreground)]">
                {row.namespace ?? "—"}
              </TableCell>
              <TableCell>
                <UtilCell value={row.cpu_util} />
              </TableCell>
              <TableCell>
                <UtilCell value={row.mem_util} />
              </TableCell>
              <TableCell className="text-right font-mono text-xs tabular-nums">
                {formatUSD(row.cost_usd)}
              </TableCell>
              <TableCell className="text-right">
                <ImpactCell value={row.impact_usd} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </SectionShell>
  );
}

// -- PvcWasteTable -----------------------------------------------------------

export function PvcWasteTable({ rows }: { rows: PvcWaste[] }) {
  const sorted = sortByImpactThenName(rows);
  return (
    <SectionShell
      id="pvc-waste"
      title="PVC waste"
      subtitle="Provisioned ≥ 1.5× used · cost > $5"
      isEmpty={sorted.length === 0}
      emptyMessage="No PVC waste in this scan."
    >
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>PVC</TableHead>
            <TableHead className="text-right">Provisioned</TableHead>
            <TableHead className="text-right">Used</TableHead>
            <TableHead>Utilization</TableHead>
            <TableHead className="text-right">Cost</TableHead>
            <TableHead className="text-right">Impact</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((row) => (
            <TableRow
              key={row.name}
              data-testid={`pvc-row-${row.name}`}
              className="hover:bg-[var(--color-accent)]/40"
            >
              <TableCell className="font-mono text-xs" title={row.name}>
                {truncName(row.name)}
              </TableCell>
              <TableCell className="text-right font-mono text-xs tabular-nums">
                {formatBytes(row.bytes_provisioned)}
              </TableCell>
              <TableCell className="text-right font-mono text-xs tabular-nums">
                {formatBytes(row.bytes_used)}
              </TableCell>
              <TableCell>
                <UtilCell value={row.utilization} />
              </TableCell>
              <TableCell className="text-right font-mono text-xs tabular-nums">
                {formatUSD(row.cost_usd)}
              </TableCell>
              <TableCell className="text-right">
                <ImpactCell value={row.impact_usd} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </SectionShell>
  );
}
