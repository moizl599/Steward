import type { ScanStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const STYLES: Record<ScanStatus, string> = {
  queued: "border-[var(--color-border)] text-[var(--color-muted-foreground)]",
  running:
    "border-[var(--color-info)]/40 bg-[var(--color-info)]/10 text-[var(--color-info)]",
  completed:
    "border-[var(--color-savings)]/40 bg-[var(--color-savings)]/10 text-[var(--color-savings)]",
  failed:
    "border-[var(--color-destructive)]/40 bg-[var(--color-destructive)]/10 text-[var(--color-destructive)]",
};

export function ScanStatusBadge({
  status,
  className,
}: {
  status: ScanStatus;
  className?: string;
}) {
  return (
    <span
      data-status={status}
      className={cn(
        "inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wider",
        STYLES[status],
        className,
      )}
    >
      {status}
    </span>
  );
}
