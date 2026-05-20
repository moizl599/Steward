"use client";

import type { Digest, NamespaceCost } from "@/lib/digest";
import { formatUSD } from "@/lib/utils";

const TOP_NS_BEFORE_OTHER = 9;

// Bar segment colours. The top namespace gets the info accent; everything
// else uses graduated neutrals from --color-border to --color-muted-foreground.
const NEUTRAL_RAMP = [
  "var(--color-muted-foreground)",
  "color-mix(in oklch, var(--color-muted-foreground) 80%, var(--color-border))",
  "color-mix(in oklch, var(--color-muted-foreground) 60%, var(--color-border))",
  "color-mix(in oklch, var(--color-muted-foreground) 45%, var(--color-border))",
  "color-mix(in oklch, var(--color-muted-foreground) 35%, var(--color-border))",
  "color-mix(in oklch, var(--color-muted-foreground) 25%, var(--color-border))",
  "color-mix(in oklch, var(--color-muted-foreground) 18%, var(--color-border))",
  "color-mix(in oklch, var(--color-muted-foreground) 12%, var(--color-border))",
  "var(--color-border)",
];

interface BarSegment {
  namespace: string;
  share: number;
  colour: string;
  cost_usd: number | null;
  isOther: boolean;
}

function buildSegments(namespaces: NamespaceCost[]): BarSegment[] {
  if (namespaces.length === 0) return [];
  const top = namespaces.slice(0, TOP_NS_BEFORE_OTHER);
  const rest = namespaces.slice(TOP_NS_BEFORE_OTHER);

  const segments: BarSegment[] = top.map((ns, idx) => ({
    namespace: ns.namespace,
    share: ns.share,
    cost_usd: ns.cost_usd,
    colour: idx === 0 ? "var(--color-info)" : NEUTRAL_RAMP[Math.min(idx, NEUTRAL_RAMP.length - 1)],
    isOther: false,
  }));

  if (rest.length > 0) {
    const remainingShare = rest.reduce((sum, ns) => sum + ns.share, 0);
    const remainingCost = rest.reduce((sum, ns) => sum + ns.cost_usd, 0);
    segments.push({
      namespace: `Other (${rest.length} namespaces)`,
      share: remainingShare,
      cost_usd: remainingCost,
      colour: "var(--color-border)",
      isOther: true,
    });
  }
  return segments;
}

interface Props {
  digest: Digest;
}

export function NamespaceBreakdown({ digest }: Props) {
  const namespaces = digest.top_namespaces_by_cost;
  const segments = buildSegments(namespaces);
  const total = digest.total_cost_usd;

  return (
    <section
      data-testid="namespace-breakdown"
      className="mt-6 rounded-md border border-[var(--color-border)] bg-[var(--color-card)] p-4"
    >
      <div className="flex items-baseline justify-between gap-4">
        <p className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-muted-foreground)]">
          Top namespaces by cost
        </p>
        <p className="font-mono text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
          <span className="font-semibold text-[var(--color-foreground)] tabular-nums">
            {formatUSD(total)}
          </span>{" "}
          total · {namespaces.length} namespace{namespaces.length === 1 ? "" : "s"}
        </p>
      </div>

      {segments.length === 0 ? (
        <p className="mt-4 text-sm text-[var(--color-muted-foreground)]">
          No allocation data in this scan.
        </p>
      ) : (
        <>
          <div
            data-testid="ns-bar"
            className="mt-4 flex h-2 w-full overflow-hidden rounded-full bg-[var(--color-border)]"
            role="img"
            aria-label="Namespace cost share"
          >
            {segments.map((seg, i) => (
              <div
                key={`${seg.namespace}-${i}`}
                style={{ width: `${seg.share * 100}%`, background: seg.colour }}
                data-testid={`ns-segment-${i}`}
                title={`${seg.namespace} — ${(seg.share * 100).toFixed(1)}%`}
              />
            ))}
          </div>

          <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
            {segments.map((seg, i) => (
              <li
                key={`${seg.namespace}-${i}-legend`}
                className="flex items-center gap-1.5"
              >
                <span
                  aria-hidden
                  className="inline-block size-2 shrink-0 rounded-[2px]"
                  style={{ background: seg.colour }}
                />
                <span className="font-mono text-xs text-[var(--color-foreground)]">
                  {seg.namespace}
                </span>
                <span className="font-mono text-[10px] tabular-nums text-[var(--color-muted-foreground)]">
                  {(seg.share * 100).toFixed(1)}%
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
