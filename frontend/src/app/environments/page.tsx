"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Play, Plus } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ConnectionStatus } from "@/components/connection-status";
import { type Environment, api } from "@/lib/api";
import { cn, formatRelative, formatUSD } from "@/lib/utils";

type SortKey = "name" | "region" | "last_scan" | "cost";
type SortDir = "asc" | "desc";

export default function EnvironmentsListPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [sortKey, setSortKey] = useState<SortKey>("last_scan");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const envs = useQuery({
    queryKey: ["environments"],
    queryFn: () => api.listEnvironments(),
  });

  const triggerScan = useMutation({
    mutationFn: ({ envId }: { envId: number }) => api.triggerScan(envId, "24h"),
    onSuccess: (scan) => {
      toast.success(`Scan #${scan.id} queued`);
      qc.invalidateQueries({ queryKey: ["environments"] });
      router.push(`/scans/${scan.id}` as Route);
    },
    onError: (err: Error) => toast.error(`Couldn't queue scan: ${err.message}`),
  });

  const sorted = envs.data ? sortEnvironments(envs.data, sortKey, sortDir) : [];

  const onSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-8 py-12">
      <div className="flex items-end justify-between border-b border-[var(--color-border)] pb-6">
        <div>
          <p className="font-mono text-xs uppercase tracking-widest text-[var(--color-muted-foreground)]">
            Environments
          </p>
          <h1 className="mt-2 font-display text-3xl font-bold tracking-tight">
            Connected clusters
          </h1>
        </div>
        <Button asChild size="sm">
          <Link href="/environments/new">
            <Plus className="size-3.5" />
            Add environment
          </Link>
        </Button>
      </div>

      <div className="mt-8">
        {envs.isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : envs.isError ? (
          <ErrorPanel
            message={(envs.error as Error).message}
            onRetry={() => envs.refetch()}
          />
        ) : sorted.length === 0 ? (
          <EmptyPanel />
        ) : (
          <div className="overflow-hidden rounded-md border border-[var(--color-border)]">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <SortableHead
                    label="Name"
                    sortKey="name"
                    activeKey={sortKey}
                    dir={sortDir}
                    onSort={onSort}
                  />
                  <TableHead>Cluster</TableHead>
                  <SortableHead
                    label="Region"
                    sortKey="region"
                    activeKey={sortKey}
                    dir={sortDir}
                    onSort={onSort}
                  />
                  <TableHead>Connection</TableHead>
                  <SortableHead
                    label="Last scan"
                    sortKey="last_scan"
                    activeKey={sortKey}
                    dir={sortDir}
                    onSort={onSort}
                    align="right"
                  />
                  <SortableHead
                    label="Cost"
                    sortKey="cost"
                    activeKey={sortKey}
                    dir={sortDir}
                    onSort={onSort}
                    align="right"
                  />
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sorted.map((env) => (
                  <TableRow
                    key={env.id}
                    className="cursor-pointer"
                    data-testid={`env-row-${env.id}`}
                    onClick={() => {
                      if (env.latest_scan)
                        router.push(`/scans/${env.latest_scan.id}` as Route);
                    }}
                  >
                    <TableCell className="font-medium">{env.name}</TableCell>
                    <TableCell className="font-mono text-xs text-[var(--color-muted-foreground)]">
                      {env.cluster_name ?? "—"}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{env.aws_region}</TableCell>
                    <TableCell>
                      <ConnectionStatus
                        ok={env.last_connection_ok}
                        lastChecked={env.last_connection_check}
                        error={env.last_connection_error}
                      />
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {env.latest_scan
                        ? formatRelative(env.latest_scan.created_at)
                        : "never"}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {env.latest_scan?.total_cost_usd != null
                        ? formatUSD(env.latest_scan.total_cost_usd)
                        : "—"}
                    </TableCell>
                    <TableCell
                      className="text-right"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Scan ${env.name}`}
                        disabled={triggerScan.isPending}
                        onClick={() => triggerScan.mutate({ envId: env.id })}
                      >
                        <Play className="size-3.5" />
                      </Button>
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

function SortableHead({
  label,
  sortKey,
  activeKey,
  dir,
  onSort,
  align = "left",
}: {
  label: string;
  sortKey: SortKey;
  activeKey: SortKey;
  dir: SortDir;
  onSort: (k: SortKey) => void;
  align?: "left" | "right";
}) {
  const active = sortKey === activeKey;
  return (
    <TableHead className={cn(align === "right" && "text-right")}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={cn(
          "inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-wider",
          active
            ? "text-[var(--color-foreground)]"
            : "text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]",
        )}
      >
        {label}
        {active ? (
          <span aria-hidden className="text-[var(--color-muted-foreground)]">
            {dir === "asc" ? "↑" : "↓"}
          </span>
        ) : null}
      </button>
    </TableHead>
  );
}

function sortEnvironments(
  envs: Environment[],
  key: SortKey,
  dir: SortDir,
): Environment[] {
  const mul = dir === "asc" ? 1 : -1;
  const cmp = (a: Environment, b: Environment): number => {
    switch (key) {
      case "name":
        return a.name.localeCompare(b.name) * mul;
      case "region":
        return a.aws_region.localeCompare(b.aws_region) * mul;
      case "last_scan": {
        const av = a.latest_scan?.created_at ?? "";
        const bv = b.latest_scan?.created_at ?? "";
        return av.localeCompare(bv) * mul;
      }
      case "cost": {
        const av = a.latest_scan?.total_cost_usd ?? -Infinity;
        const bv = b.latest_scan?.total_cost_usd ?? -Infinity;
        return (av - bv) * mul;
      }
    }
  };
  return [...envs].sort(cmp);
}

function ErrorPanel({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="rounded border border-[var(--color-destructive)]/40 bg-[var(--color-destructive)]/10 p-4">
      <p className="font-medium text-[var(--color-destructive)]">
        Couldn&apos;t load environments
      </p>
      <p className="mt-1 font-mono text-xs text-[var(--color-muted-foreground)]">
        {message}
      </p>
      <Button onClick={onRetry} variant="outline" size="sm" className="mt-3">
        Retry
      </Button>
    </div>
  );
}

function EmptyPanel() {
  return (
    <div className="rounded border border-dashed border-[var(--color-border)] bg-[var(--color-card)]/40 px-8 py-16 text-center">
      <h2 className="font-display text-xl font-bold tracking-tight">
        No environments yet
      </h2>
      <p className="mt-2 text-sm text-[var(--color-muted-foreground)]">
        Connect your first Kubecost instance to get started.
      </p>
      <Button asChild className="mt-6">
        <Link href="/environments/new">
          <Plus className="size-3.5" />
          Add environment
        </Link>
      </Button>
    </div>
  );
}
