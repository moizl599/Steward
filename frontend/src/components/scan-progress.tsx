import type { ScanStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const PHASES = [
  { key: "Connecting to Kubecost", label: "Connect" },
  { key: "Building digest", label: "Digest" },
  { key: "Retrieving knowledge", label: "Retrieve" },
  { key: "Analyzing", label: "Analyze" },
] as const;

function phaseIndex(progress: string | null): number {
  if (!progress) return -1;
  for (let i = PHASES.length - 1; i >= 0; i--) {
    if (progress.startsWith(PHASES[i].key)) return i;
  }
  return -1;
}

export interface ScanProgressProps {
  status: ScanStatus;
  progressMessage: string | null;
  className?: string;
}

export function ScanProgress({ status, progressMessage, className }: ScanProgressProps) {
  const active = phaseIndex(progressMessage);
  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex items-center gap-3">
        <span className="size-2 animate-pulse rounded-full bg-[var(--color-info)]" aria-hidden />
        <span className="font-mono text-xs uppercase tracking-widest text-[var(--color-muted-foreground)]">
          {status === "queued" ? "Queued" : "Running"}
        </span>
        <span className="text-sm">{progressMessage ?? "Starting"}</span>
      </div>
      <div className="flex gap-1.5">
        {PHASES.map((phase, idx) => {
          const state = idx < active ? "done" : idx === active ? "active" : "pending";
          return (
            <div key={phase.key} className="flex-1">
              <div
                className={cn(
                  "h-1 rounded-full",
                  state === "done" && "bg-[var(--color-savings)]",
                  state === "active" && "bg-[var(--color-info)]",
                  state === "pending" && "bg-[var(--color-border)]",
                )}
              />
              <p
                className={cn(
                  "mt-1.5 font-mono text-[10px] uppercase tracking-wider",
                  state === "pending"
                    ? "text-[var(--color-muted-foreground)]"
                    : "text-[var(--color-foreground)]",
                )}
              >
                {phase.label}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
