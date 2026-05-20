import type { Severity } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Severity → visual mapping.
 *
 * Critical/high lean on the waste token (red).
 * Medium uses the warn token (amber).
 * Low/info use the info token (blue) at decreasing intensity.
 * Unknown falls back to the muted token (neutral).
 */
const STYLES: Record<Severity, string> = {
  critical:
    "bg-[oklch(0.62_0.22_27_/_0.18)] text-[var(--color-waste)] border-[var(--color-waste)]/40",
  high:
    "bg-[oklch(0.62_0.22_27_/_0.10)] text-[oklch(0.78_0.18_45)] border-[oklch(0.78_0.18_45)]/40",
  medium:
    "bg-[oklch(0.78_0.16_85_/_0.12)] text-[var(--color-warn)] border-[var(--color-warn)]/40",
  low:
    "bg-[oklch(0.62_0.18_244_/_0.12)] text-[var(--color-info)] border-[var(--color-info)]/40",
  info:
    "bg-[var(--color-muted)] text-[var(--color-muted-foreground)] border-transparent",
};

export interface SeverityBadgeProps {
  severity: Severity;
  className?: string;
}

export function SeverityBadge({ severity, className }: SeverityBadgeProps) {
  return (
    <span
      data-severity={severity}
      className={cn(
        "inline-flex items-center rounded border px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wider",
        STYLES[severity],
        className,
      )}
    >
      {severity}
    </span>
  );
}
