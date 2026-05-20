import { cn, formatRelative } from "@/lib/utils";

type Status = "ok" | "stale" | "error" | "unknown";

export const STALE_CONNECTION_THRESHOLD_MS = 24 * 60 * 60 * 1000;

export interface ConnectionStatusProps {
  ok: boolean;
  lastChecked: string | null;
  error?: string | null;
  className?: string;
}

const DOT_CLASSES: Record<Status, string> = {
  ok: "bg-[var(--color-savings)]",
  stale: "bg-[var(--color-warn)]",
  error: "bg-[var(--color-waste)]",
  unknown: "bg-[var(--color-muted-foreground)]",
};

function resolveStatus(ok: boolean, lastChecked: string | null): Status {
  if (lastChecked == null) return "unknown";
  if (!ok) return "error";
  const age = Date.now() - new Date(lastChecked).getTime();
  return age > STALE_CONNECTION_THRESHOLD_MS ? "stale" : "ok";
}

export function ConnectionStatus({ ok, lastChecked, error, className }: ConnectionStatusProps) {
  const status = resolveStatus(ok, lastChecked);
  const relative = lastChecked ? formatRelative(lastChecked) : null;
  const label =
    status === "unknown"
      ? "unknown"
      : status === "ok"
        ? `checked ${relative}`
        : status === "stale"
          ? `stale · checked ${relative}`
          : `failed ${relative}`;

  return (
    <span
      className={cn("inline-flex items-center gap-1.5 text-xs", className)}
      title={error ?? undefined}
    >
      <span
        className={cn("size-2 rounded-full", DOT_CLASSES[status])}
        aria-hidden
        data-status={status}
      />
      <span className="font-mono text-[var(--color-muted-foreground)]">{label}</span>
    </span>
  );
}
