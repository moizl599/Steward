"use client";

import { useQuery } from "@tanstack/react-query";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Plus, Play } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ConnectionStatus } from "@/components/connection-status";
import { type Environment, api } from "@/lib/api";
import { cn, formatRelative, formatUSD } from "@/lib/utils";

export default function DashboardPage() {
  const envs = useQuery({
    queryKey: ["environments"],
    queryFn: () => api.listEnvironments(),
  });

  return (
    <div className="mx-auto max-w-6xl px-8 py-12">
      <DashboardHeader />

      {envs.data && envs.data.length > 0 ? <DashboardSummary envs={envs.data} /> : null}

      <div className="mt-10">
        {envs.isLoading ? (
          <CardGrid>
            {[0, 1].map((i) => (
              <SkeletonCard key={i} />
            ))}
          </CardGrid>
        ) : envs.isError ? (
          <ErrorState message={(envs.error as Error).message} onRetry={() => envs.refetch()} />
        ) : envs.data && envs.data.length > 0 ? (
          <CardGrid>
            {envs.data.map((env) => (
              <EnvironmentCard key={env.id} env={env} />
            ))}
          </CardGrid>
        ) : (
          <EmptyState />
        )}
      </div>
    </div>
  );
}

export function DashboardSummary({ envs }: { envs: Environment[] }) {
  if (envs.length === 0) return null;

  const totalCost = envs.reduce((sum, e) => {
    const latest = e.latest_scan;
    if (!latest || latest.status !== "completed" || latest.total_cost_usd == null) {
      return sum;
    }
    return sum + latest.total_cost_usd;
  }, 0);
  const windows = new Set(
    envs
      .map((e) =>
        e.latest_scan && e.latest_scan.status === "completed" ? e.latest_scan.window : null,
      )
      .filter((w): w is string => w != null),
  );
  const costWindow = windows.size === 1 ? [...windows][0] : "latest";

  const openFindings = envs.reduce((sum, e) => sum + (e.latest_scan?.finding_count ?? 0), 0);
  const activeScans = envs.filter(
    (e) => e.latest_scan?.status === "queued" || e.latest_scan?.status === "running",
  ).length;

  const items: string[] = [
    `${envs.length} environment${envs.length === 1 ? "" : "s"}`,
    `${formatUSD(totalCost)} / ${costWindow} total`,
    `${openFindings} open finding${openFindings === 1 ? "" : "s"}`,
  ];
  if (activeScans > 0) {
    items.push(`${activeScans} scan${activeScans === 1 ? "" : "s"} running`);
  }

  return (
    <p
      className="mt-4 font-mono text-xs uppercase tracking-wider text-[var(--color-muted-foreground)]"
      data-testid="dashboard-summary"
    >
      {items.join("  ·  ")}
    </p>
  );
}

function DashboardHeader() {
  return (
    <div className="flex items-end justify-between border-b border-[var(--color-border)] pb-6">
      <div>
        <p className="font-mono text-xs uppercase tracking-widest text-[var(--color-muted-foreground)]">
          Overview
        </p>
        <h1 className="mt-2 font-display text-3xl font-bold tracking-tight">Dashboard</h1>
      </div>
      <Button asChild size="sm" variant="outline">
        <Link href="/environments/new">
          <Plus className="size-3.5" />
          New environment
        </Link>
      </Button>
    </div>
  );
}

function CardGrid({ children }: { children: React.ReactNode }) {
  return <div className="grid gap-4 md:grid-cols-2">{children}</div>;
}

function EnvironmentCard({ env }: { env: Environment }) {
  const router = useRouter();
  const latest = env.latest_scan;
  const onScanClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (latest) router.push(`/scans/${latest.id}` as Route);
    else router.push(`/environments/${env.id}` as Route);
  };
  const onCardClick = () => {
    if (latest) router.push(`/scans/${latest.id}` as Route);
  };
  return (
    <article
      onClick={onCardClick}
      className={cn(
        "group rounded-md border border-[var(--color-border)] bg-[var(--color-card)] p-5 transition-colors",
        latest && "cursor-pointer hover:border-[var(--color-muted-foreground)]/40",
      )}
      data-testid={`env-card-${env.id}`}
    >
      {latest ? <span className="sr-only">View latest report</span> : null}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h2 className="font-display text-xl font-bold tracking-tight">{env.name}</h2>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <span className="rounded border border-[var(--color-border)] bg-[var(--color-background)] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
              {env.aws_region}
            </span>
            {env.cluster_name ? (
              <span className="rounded border border-[var(--color-border)] bg-[var(--color-background)] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
                {env.cluster_name}
              </span>
            ) : null}
          </div>
        </div>
        <Button
          size="sm"
          variant="default"
          onClick={onScanClick}
          aria-label={`Scan ${env.name}`}
        >
          <Play className="size-3" />
          Scan
        </Button>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-4 border-t border-[var(--color-border)] pt-4 text-sm">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
            Connection
          </p>
          <ConnectionStatus
            ok={env.last_connection_ok}
            lastChecked={env.last_connection_check}
            error={env.last_connection_error}
            className="mt-1"
          />
        </div>
        <div>
          <p className="font-mono text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
            Last scan
          </p>
          {latest ? (
            <div className="mt-1 flex items-baseline gap-2">
              {latest.status === "completed" && latest.total_cost_usd != null ? (
                <span className="font-mono text-base font-semibold tabular-nums">
                  {formatUSD(latest.total_cost_usd)}
                </span>
              ) : (
                <span className="font-mono text-xs uppercase tracking-wider text-[var(--color-muted-foreground)]">
                  {latest.status}
                </span>
              )}
              <span className="font-mono text-xs text-[var(--color-muted-foreground)]">
                / {latest.window} · {formatRelative(latest.created_at)}
              </span>
            </div>
          ) : (
            <p className="mt-1 font-mono text-xs text-[var(--color-muted-foreground)]">
              never scanned
            </p>
          )}
        </div>
      </div>

      {latest ? (
        <div className="mt-3 flex items-center gap-1 text-xs text-[var(--color-muted-foreground)] opacity-60 transition-opacity group-hover:opacity-100">
          View report <ArrowRight className="size-3" />
        </div>
      ) : null}
    </article>
  );
}

function SkeletonCard() {
  return (
    <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-card)] p-5">
      <Skeleton className="h-6 w-1/2" />
      <Skeleton className="mt-2 h-4 w-1/3" />
      <Skeleton className="mt-6 h-12 w-full" />
    </div>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="rounded border border-[var(--color-destructive)]/40 bg-[var(--color-destructive)]/10 px-5 py-4">
      <p className="text-sm font-medium text-[var(--color-destructive)]">
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

function EmptyState() {
  return (
    <div className="rounded border border-dashed border-[var(--color-border)] bg-[var(--color-card)]/40 px-8 py-16 text-center">
      <h2 className="font-display text-xl font-bold tracking-tight">
        No environments yet
      </h2>
      <p className="mt-2 text-sm text-[var(--color-muted-foreground)]">
        Connect your first Kubecost instance to start analyzing costs.
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
