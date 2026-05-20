"use client";

import { useQuery } from "@tanstack/react-query";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { ScanStatusBadge } from "@/components/scan-status-badge";
import { type ScanStatus, type ScanWithEnv, api } from "@/lib/api";
import { cn, formatDateTime, formatRelative, formatUSD } from "@/lib/utils";

type Filters = {
  env_id: number | null;
  status: ScanStatus | null;
  from: string | null;
  to: string | null;
};

const EMPTY_FILTERS: Filters = { env_id: null, status: null, from: null, to: null };

export default function ReportsPage() {
  const router = useRouter();
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);

  const envs = useQuery({
    queryKey: ["environments"],
    queryFn: () => api.listEnvironments(),
  });

  const scans = useQuery({
    queryKey: ["scans", filters],
    queryFn: () => api.listAllScans(filters),
  });

  const trend = useMemo(() => buildTrend(scans.data ?? []), [scans.data]);

  return (
    <div className="mx-auto max-w-6xl px-8 py-12">
      <div className="flex items-end justify-between border-b border-[var(--color-border)] pb-6">
        <div>
          <p className="font-mono text-xs uppercase tracking-widest text-[var(--color-muted-foreground)]">
            History
          </p>
          <h1 className="mt-2 font-display text-3xl font-bold tracking-tight">
            Reports
          </h1>
        </div>
      </div>

      <FilterBar
        filters={filters}
        envs={envs.data ?? []}
        onChange={(next) => setFilters((prev) => ({ ...prev, ...next }))}
        onReset={() => setFilters(EMPTY_FILTERS)}
      />

      <TrendChart points={trend} />

      <div className="mt-8">
        {scans.isLoading ? (
          <Skeleton className="h-48 w-full" />
        ) : scans.isError ? (
          <p className="text-sm text-[var(--color-destructive)]">
            {(scans.error as Error).message}
          </p>
        ) : !scans.data || scans.data.length === 0 ? (
          <div className="rounded border border-dashed border-[var(--color-border)] bg-[var(--color-card)]/40 px-8 py-12 text-center">
            <p className="font-mono text-xs uppercase tracking-widest text-[var(--color-muted-foreground)]">
              No scans match
            </p>
            <p className="mt-2 text-sm">Adjust the filters or trigger a scan.</p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-md border border-[var(--color-border)]">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-16">ID</TableHead>
                  <TableHead>Environment</TableHead>
                  <TableHead>Window</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Completed</TableHead>
                  <TableHead className="text-right">Cost</TableHead>
                  <TableHead className="text-right">Findings</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {scans.data.map((s) => (
                  <TableRow
                    key={s.id}
                    className="cursor-pointer"
                    data-testid={`scan-row-${s.id}`}
                    onClick={() => router.push(`/scans/${s.id}` as Route)}
                  >
                    <TableCell className="font-mono text-xs text-[var(--color-muted-foreground)]">
                      #{s.id}
                    </TableCell>
                    <TableCell className="font-medium">
                      {s.environment_name ?? `env ${s.environment_id}`}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{s.window}</TableCell>
                    <TableCell>
                      <ScanStatusBadge status={s.status} />
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {s.started_at ? formatRelative(s.started_at) : "—"}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {s.completed_at ? formatDateTime(s.completed_at) : "—"}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {s.total_cost_usd != null ? formatUSD(s.total_cost_usd) : "—"}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {s.finding_count ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </div>
  );
}

// -- Filters -----------------------------------------------------------------

const ALL = "__all__";

function FilterBar({
  filters,
  envs,
  onChange,
  onReset,
}: {
  filters: Filters;
  envs: { id: number; name: string }[];
  onChange: (patch: Partial<Filters>) => void;
  onReset: () => void;
}) {
  return (
    <div
      className="mt-6 flex flex-wrap items-end gap-4 rounded-md border border-[var(--color-border)] bg-[var(--color-card)] p-4"
      data-testid="filter-bar"
    >
      <FilterField label="Environment">
        <Select
          value={filters.env_id?.toString() ?? ALL}
          onValueChange={(v) =>
            onChange({ env_id: v === ALL ? null : Number(v) })
          }
        >
          <SelectTrigger
            size="sm"
            className="w-44 font-mono text-xs"
            data-testid="filter-env"
          >
            <SelectValue placeholder="All environments" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All environments</SelectItem>
            {envs.map((e) => (
              <SelectItem key={e.id} value={e.id.toString()}>
                {e.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FilterField>

      <FilterField label="Status">
        <Select
          value={filters.status ?? ALL}
          onValueChange={(v) =>
            onChange({ status: v === ALL ? null : (v as ScanStatus) })
          }
        >
          <SelectTrigger
            size="sm"
            className="w-32 font-mono text-xs"
            data-testid="filter-status"
          >
            <SelectValue placeholder="Any" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Any status</SelectItem>
            <SelectItem value="queued">Queued</SelectItem>
            <SelectItem value="running">Running</SelectItem>
            <SelectItem value="completed">Completed</SelectItem>
            <SelectItem value="failed">Failed</SelectItem>
          </SelectContent>
        </Select>
      </FilterField>

      <FilterField label="From">
        <Input
          type="date"
          className="w-40 font-mono text-xs"
          value={filters.from ?? ""}
          onChange={(e) => onChange({ from: e.target.value || null })}
          data-testid="filter-from"
        />
      </FilterField>

      <FilterField label="To">
        <Input
          type="date"
          className="w-40 font-mono text-xs"
          value={filters.to ?? ""}
          onChange={(e) => onChange({ to: e.target.value || null })}
          data-testid="filter-to"
        />
      </FilterField>

      <button
        type="button"
        onClick={onReset}
        className="ml-auto self-end font-mono text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]"
      >
        Reset
      </button>
    </div>
  );
}

function FilterField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="font-mono text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
        {label}
      </span>
      {children}
    </div>
  );
}

// -- Chart -------------------------------------------------------------------

interface TrendPoint {
  ts: number;
  label: string;
  cost: number;
}

function buildTrend(scans: ScanWithEnv[]): TrendPoint[] {
  const completed = scans
    .filter((s) => s.status === "completed" && s.total_cost_usd != null)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
  return completed.map((s) => ({
    ts: new Date(s.created_at).getTime(),
    label: formatDateTime(s.created_at),
    cost: s.total_cost_usd ?? 0,
  }));
}

function TrendChart({ points }: { points: TrendPoint[] }) {
  if (points.length < 2) {
    return (
      <div
        data-testid="trend-placeholder"
        className={cn(
          "mt-6 flex h-44 items-center justify-center rounded-md border border-dashed",
          "border-[var(--color-border)] bg-[var(--color-card)]/40",
        )}
      >
        <p className="font-mono text-xs uppercase tracking-widest text-[var(--color-muted-foreground)]">
          Need at least 2 completed scans for trends
        </p>
      </div>
    );
  }
  return (
    <div
      className="mt-6 rounded-md border border-[var(--color-border)] bg-[var(--color-card)] p-4"
      data-testid="trend-chart"
    >
      <p className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-muted-foreground)]">
        Total cost over time
      </p>
      <div className="mt-3 h-44">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
            <CartesianGrid stroke="var(--color-border)" strokeDasharray="2 4" />
            <XAxis
              dataKey="ts"
              type="number"
              domain={["auto", "auto"]}
              scale="time"
              tickFormatter={(t) => formatRelative(new Date(t))}
              tick={{ fill: "var(--color-muted-foreground)", fontSize: 10 }}
              stroke="var(--color-border)"
            />
            <YAxis
              tick={{ fill: "var(--color-muted-foreground)", fontSize: 10 }}
              stroke="var(--color-border)"
              tickFormatter={(v) => formatUSD(v)}
            />
            <Tooltip
              contentStyle={{
                background: "var(--color-popover)",
                border: "1px solid var(--color-border)",
                borderRadius: "var(--radius)",
                fontFamily: "var(--font-mono)",
                fontSize: "12px",
              }}
              labelFormatter={(_, payload) => payload?.[0]?.payload?.label ?? ""}
              formatter={(v: number) => [formatUSD(v), "cost"]}
            />
            <Line
              type="monotone"
              dataKey="cost"
              stroke="var(--color-savings)"
              strokeWidth={1.5}
              dot={{ r: 2.5, fill: "var(--color-savings)" }}
              activeDot={{ r: 4 }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
