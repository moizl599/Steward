"use client";

interface ScanFooterProps {
  modelUsed: string;
  durationMs?: number | null;
  promptTokens?: number | null;
  completionTokens?: number | null;
}

/**
 * Single-row mono small-text footer at the bottom of the report page. Pulls
 * scan-execution metadata that used to live in the executive summary card —
 * keeps the executive summary itself focused on prose.
 *
 * Optional metrics fall back to em-dashes so the layout stays stable when
 * older Report rows have null observability fields.
 */
export function ScanFooter({
  modelUsed,
  durationMs,
  promptTokens,
  completionTokens,
}: ScanFooterProps) {
  return (
    <footer
      data-testid="scan-footer"
      className="mt-10 flex flex-wrap items-center justify-between gap-x-6 gap-y-1 border-t border-[var(--color-border)] pt-4 font-mono text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]"
    >
      <span>
        Scan_Duration:{" "}
        <span className="tabular-nums text-[var(--color-foreground)]">
          {durationMs != null ? `${(durationMs / 1000).toFixed(1)}s` : "—"}
        </span>
        {" · "}
        Tokens:{" "}
        <span className="tabular-nums text-[var(--color-foreground)]">
          {promptTokens != null ? promptTokens.toLocaleString() : "—"}
        </span>{" "}
        in /{" "}
        <span className="tabular-nums text-[var(--color-foreground)]">
          {completionTokens != null ? completionTokens.toLocaleString() : "—"}
        </span>{" "}
        out
      </span>
      <span>
        Model: <span className="text-[var(--color-foreground)]">{modelUsed}</span>
      </span>
    </footer>
  );
}
