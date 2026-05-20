"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import type { Route } from "next";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, RotateCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ConnectionStatus } from "@/components/connection-status";
import { ScanProgress } from "@/components/scan-progress";
import {
  type Environment,
  type Report,
  type Scan,
  api,
} from "@/lib/api";
import { parseDigest, type Digest, type RawData } from "@/lib/digest";
import { cn, formatRelative, formatUSD } from "@/lib/utils";

import { AtAGlance, ScalePill } from "@/components/scan-report/at-a-glance";
import { NamespaceBreakdown } from "@/components/scan-report/namespace-breakdown";
import {
  FindingCard,
  sortFindings,
} from "@/components/scan-report/finding-card";
import { RawDataTabs } from "@/components/scan-report/raw-data-tabs";
import { ScanFooter } from "@/components/scan-report/scan-footer";
import {
  IdleWorkloadsTable,
  OverProvisionedTable,
  PvcWasteTable,
} from "@/components/scan-report/workload-table";

export default function ScanDetailPage() {
  const params = useParams<{ id: string }>();
  const scanId = Number(params.id);

  const scan = useQuery<Scan>({
    queryKey: ["scan", scanId],
    queryFn: () => api.getScan(scanId),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "queued" || s === "running" ? 2000 : false;
    },
  });

  const env = useQuery<Environment>({
    queryKey: ["environment", scan.data?.environment_id],
    queryFn: () => api.getEnvironment(scan.data!.environment_id),
    enabled: scan.data != null,
  });

  if (scan.isLoading) {
    return <LoadingShell />;
  }
  if (scan.isError || !scan.data) {
    return (
      <ScanErrorShell
        error={(scan.error as Error)?.message ?? "Failed to load scan"}
      />
    );
  }

  const s = scan.data;

  return (
    <div className="mx-auto max-w-5xl px-8 py-12">
      <BackToDashboard />

      {s.status === "queued" || s.status === "running" ? (
        <>
          <RunningHeader scan={s} env={env.data ?? null} />
          <div className="mt-10">
            <ScanProgress
              status={s.status}
              progressMessage={s.progress_message}
              className="rounded border border-[var(--color-border)] bg-[var(--color-card)] p-6"
            />
          </div>
        </>
      ) : s.status === "failed" ? (
        <>
          <RunningHeader scan={s} env={env.data ?? null} />
          <div className="mt-10">
            <ScanFailedView scan={s} />
          </div>
        </>
      ) : (
        <ScanCompletedView scan={s} env={env.data ?? null} />
      )}
    </div>
  );
}

function BackToDashboard() {
  return (
    <Button asChild variant="ghost" size="sm" className="-ml-3 mb-2">
      <Link href="/">
        <ArrowLeft className="size-3" />
        Back
      </Link>
    </Button>
  );
}

// -- Completed view ----------------------------------------------------------

function ScanCompletedView({
  scan,
  env,
}: {
  scan: Scan;
  env: Environment | null;
}) {
  const report = useQuery<Report>({
    queryKey: ["report", scan.id],
    queryFn: () => api.getReport(scan.id),
  });
  const digestQ = useQuery({
    queryKey: ["digest", scan.id],
    queryFn: () => api.getDigest(scan.id),
  });
  const rawDataQ = useQuery({
    queryKey: ["raw-data", scan.id],
    queryFn: () => api.getRawData(scan.id),
    // raw_data is only meaningful for completed scans; the endpoint 409s
    // otherwise and we don't want red-herring error states.
    enabled: scan.status === "completed",
    // Treat a 409 (transient: scan flipped state) the same as unavailable
    // rather than surfacing as an error banner.
    retry: false,
  });

  if (report.isLoading) {
    return <CompletedLoadingShell scan={scan} env={env} />;
  }
  if (report.isError) {
    return (
      <>
        <CompletedHeader scan={scan} env={env} digest={null} />
        <div className="mt-8 rounded border border-[var(--color-destructive)]/40 bg-[var(--color-destructive)]/10 p-4 text-sm text-[var(--color-destructive)]">
          Couldn&apos;t load the report: {(report.error as Error).message}
        </div>
      </>
    );
  }
  if (!report.data) return null;

  const digest = parseDigest(digestQ.data ?? null);
  // ``GET /scans/{id}/raw-data`` returns either the four Kubecost slices or a
  // ``{truncated, original_bytes}`` sentinel. Errors (e.g. 409 mid-flight) and
  // null fall through to the "unavailable" placeholder in RawDataTabs.
  const rawData: RawData | null = rawDataQ.data ?? null;

  const sortedFindings = sortFindings(report.data.findings);
  const healthyVariant =
    sortedFindings.length === 1 &&
    sortedFindings[0].severity === "info" &&
    digest?.efficiency_grade === "healthy";

  return (
    <>
      <CompletedHeader scan={scan} env={env} digest={digest} />

      {digest ? <AtAGlance digest={digest} /> : null}
      {digest ? <NamespaceBreakdown digest={digest} /> : null}

      <ExecutiveSummary report={report.data} />
      <FindingsList findings={sortedFindings} healthyVariant={healthyVariant} />

      {digest ? <IdleWorkloadsTable rows={digest.idle_workloads} /> : null}
      {digest ? <OverProvisionedTable rows={digest.over_provisioned} /> : null}
      {digest ? <PvcWasteTable rows={digest.pvc_waste} /> : null}

      <RawDataTabs digest={digest} rawData={rawData} />

      <ScanFooter
        modelUsed={report.data.model_used}
        durationMs={report.data.duration_ms}
        promptTokens={report.data.prompt_tokens}
        completionTokens={report.data.completion_tokens}
      />
    </>
  );
}

// -- Headers -----------------------------------------------------------------

function CompletedHeader({
  scan,
  env,
  digest,
}: {
  scan: Scan;
  env: Environment | null;
  digest: Digest | null;
}) {
  const totalCost =
    scan.total_cost_usd != null ? formatUSD(scan.total_cost_usd) : "—";
  return (
    <div className="border-b border-[var(--color-border)] pb-6">
      <p className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-muted-foreground)]">
        Scan #{scan.id} · Cost analysis
      </p>
      <h1 className="mt-2 font-display text-3xl font-bold tracking-tight">
        {env?.name ?? "Cost analysis"}
      </h1>
      <div className="mt-4 flex flex-wrap items-baseline gap-x-4 gap-y-2">
        <p className="font-display text-4xl font-bold tabular-nums">
          {totalCost}
          <span className="ml-1 font-mono text-base font-normal text-[var(--color-muted-foreground)]">
            / {scan.window}
          </span>
        </p>
        {digest ? <ScalePill scale={digest.cluster_scale} /> : null}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
        {digest ? (
          <>
            <span className="tabular-nums text-[var(--color-foreground)]">
              ≈ {formatUSD(digest.monthly_run_rate_usd)} / mo
            </span>
            <Dot />
          </>
        ) : null}
        {scan.completed_at ? (
          <>
            <span className="tabular-nums">
              {formatRelative(scan.completed_at)}
            </span>
            <Dot />
          </>
        ) : null}
        {env ? (
          <ConnectionStatus
            ok={env.last_connection_ok}
            lastChecked={env.last_connection_check}
            error={env.last_connection_error}
          />
        ) : null}
      </div>
    </div>
  );
}

function RunningHeader({
  scan,
  env,
}: {
  scan: Scan;
  env: Environment | null;
}) {
  return (
    <div className="border-b border-[var(--color-border)] pb-6">
      <p className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-muted-foreground)]">
        Scan #{scan.id} · Cost analysis
      </p>
      <h1 className="mt-2 font-display text-3xl font-bold tracking-tight">
        {env?.name ?? `Scan #${scan.id}`}
      </h1>
      <p className="mt-3 font-mono text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
        Window <span className="text-[var(--color-foreground)]">{scan.window}</span>
      </p>
    </div>
  );
}

function Dot() {
  return <span className="text-[var(--color-border)]">·</span>;
}

// -- Executive summary -------------------------------------------------------

function ExecutiveSummary({ report }: { report: Report }) {
  return (
    <section className="mt-8 rounded-md border border-[var(--color-border)] bg-[var(--color-card)] p-7">
      <p className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-muted-foreground)]">
        Executive summary
      </p>
      <p className="mt-3 text-base leading-relaxed text-[var(--color-foreground)]">
        {report.executive_summary}
      </p>
      {report.estimated_monthly_savings_usd != null &&
      report.estimated_monthly_savings_usd > 0 ? (
        <div className="mt-6 border-t border-[var(--color-border)] pt-4">
          <p className="font-mono text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
            Estimated monthly savings
          </p>
          <p
            data-testid="exec-savings"
            className="mt-0.5 font-mono text-2xl font-bold tabular-nums text-[var(--color-savings)]"
          >
            {formatUSD(report.estimated_monthly_savings_usd)}
          </p>
        </div>
      ) : null}
    </section>
  );
}

// -- Findings list -----------------------------------------------------------

function FindingsList({
  findings,
  healthyVariant,
}: {
  findings: Report["findings"];
  healthyVariant: boolean;
}) {
  if (findings.length === 0) {
    return (
      <section className="mt-8">
        <p className="font-mono text-xs uppercase tracking-widest text-[var(--color-muted-foreground)]">
          Findings
        </p>
        <p className="mt-3 text-sm text-[var(--color-muted-foreground)]">
          No findings worth surfacing.
        </p>
      </section>
    );
  }
  return (
    <section className="mt-8">
      <p className="font-mono text-xs uppercase tracking-widest text-[var(--color-muted-foreground)]">
        Findings ({findings.length})
      </p>
      <ul className="mt-3 space-y-3">
        {findings.map((f, i) => (
          <FindingCard
            key={i}
            finding={f}
            healthyVariant={healthyVariant}
          />
        ))}
      </ul>
    </section>
  );
}

// -- Failed view -------------------------------------------------------------

function ScanFailedView({ scan }: { scan: Scan }) {
  const router = useRouter();
  const retry = useMutation({
    mutationFn: () => api.triggerScan(scan.environment_id, scan.window),
    onSuccess: (newScan) => {
      router.push(`/scans/${newScan.id}` as Route);
    },
  });

  return (
    <div className="space-y-4">
      <div
        role="alert"
        data-testid="scan-failed-banner"
        className="rounded-md border border-[var(--color-destructive)]/40 bg-[var(--color-destructive)]/10 p-5"
      >
        <p className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-destructive)]">
          Scan failed
        </p>
        <p className="mt-2 font-mono text-sm text-[var(--color-destructive)]">
          {scan.error_message ?? "(no error message recorded)"}
        </p>
      </div>
      <Button onClick={() => retry.mutate()} disabled={retry.isPending}>
        <RotateCw className="size-3" />
        {retry.isPending ? "Retrying…" : `Retry scan (${scan.window})`}
      </Button>
    </div>
  );
}

// -- Loading shells ----------------------------------------------------------

function LoadingShell() {
  return (
    <div className="mx-auto max-w-5xl px-8 py-12">
      {/* Eyebrow + hero block */}
      <Skeleton className="h-3 w-44" />
      <Skeleton className="mt-3 h-8 w-2/3" />
      <Skeleton className="mt-3 h-10 w-40" />
      {/* AtAGlance row */}
      <div className="mt-8 grid gap-3 md:grid-cols-[1fr_1.4fr_1fr]">
        <Skeleton className={cardShell} />
        <Skeleton className={cardShell} />
        <Skeleton className={cardShell} />
      </div>
      {/* Namespace bar */}
      <Skeleton className="mt-6 h-20 w-full" />
      {/* Summary card */}
      <Skeleton className="mt-8 h-32 w-full" />
      {/* Three finding card placeholders */}
      <div className="mt-3 space-y-3">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    </div>
  );
}

const cardShell = "h-32 w-full";

function CompletedLoadingShell({
  scan,
  env,
}: {
  scan: Scan;
  env: Environment | null;
}) {
  return (
    <>
      <CompletedHeader scan={scan} env={env} digest={null} />
      <div className="mt-8 grid gap-3 md:grid-cols-[1fr_1.4fr_1fr]">
        <Skeleton className={cardShell} />
        <Skeleton className={cardShell} />
        <Skeleton className={cardShell} />
      </div>
      <Skeleton className="mt-6 h-20 w-full" />
      <Skeleton className="mt-8 h-32 w-full" />
    </>
  );
}

function ScanErrorShell({ error }: { error: string }) {
  return (
    <div className={cn("mx-auto max-w-5xl px-8 py-12")}>
      <BackToDashboard />
      <div className="rounded border border-[var(--color-destructive)]/40 bg-[var(--color-destructive)]/10 p-5">
        <p className="font-medium text-[var(--color-destructive)]">
          Couldn&apos;t load scan
        </p>
        <p className="mt-1 font-mono text-xs text-[var(--color-muted-foreground)]">
          {error}
        </p>
      </div>
    </div>
  );
}
