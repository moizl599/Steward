"use client";

import { useMemo, useState } from "react";

import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import type { Digest, RawData } from "@/lib/digest";

type TabKey = "allocation" | "assets" | "savings" | "digest";

interface RawDataTabsProps {
  digest: Digest | null;
  rawData?: RawData | null;
}

const TAB_DEFINITIONS: { key: TabKey; label: string; source: TabKey }[] = [
  { key: "allocation", label: "Allocation", source: "allocation" },
  { key: "assets", label: "Assets", source: "assets" },
  { key: "savings", label: "Savings", source: "savings" },
  { key: "digest", label: "Full digest", source: "digest" },
];

export function RawDataTabs({ digest, rawData }: RawDataTabsProps) {
  const [active, setActive] = useState<TabKey>("allocation");
  const truncated = rawData?.truncated === true;
  const originalBytes = rawData?.original_bytes;

  const formatted = useMemo(() => {
    return stringifyForTab(active, { digest, rawData, truncated });
  }, [active, digest, rawData, truncated]);

  return (
    <section className="mt-8" data-testid="raw-data-tabs">
      <p className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-muted-foreground)]">
        Raw Kubecost data
      </p>
      <Tabs
        value={active}
        onValueChange={(v) => setActive(v as TabKey)}
        className="mt-3"
      >
        <TabsList>
          {TAB_DEFINITIONS.map((tab) => (
            <TabsTrigger
              key={tab.key}
              value={tab.key}
              data-testid={`raw-tab-${tab.key}`}
            >
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>

        {TAB_DEFINITIONS.map((tab) => (
          <TabsContent key={tab.key} value={tab.key} className="mt-3">
            <TabBody
              tab={tab.key}
              formatted={formatted}
              truncated={truncated}
              originalBytes={originalBytes}
              hasRawData={rawData != null}
              hasDigest={digest != null}
            />
          </TabsContent>
        ))}
      </Tabs>
    </section>
  );
}

function TabBody({
  tab,
  formatted,
  truncated,
  originalBytes,
  hasRawData,
  hasDigest,
}: {
  tab: TabKey;
  formatted: string;
  truncated: boolean;
  originalBytes: number | undefined;
  hasRawData: boolean;
  hasDigest: boolean;
}) {
  if (tab !== "digest" && truncated) {
    return (
      <p
        data-testid={`raw-${tab}-truncated`}
        className="rounded-md border border-[var(--color-border)] bg-[var(--color-card)]/40 px-4 py-3 text-sm text-[var(--color-muted-foreground)]"
      >
        Raw data was truncated; size:{" "}
        <span className="font-mono tabular-nums">
          {originalBytes != null ? `${originalBytes.toLocaleString()} bytes` : "unknown"}
        </span>
        . Inspect via the backend logs.
      </p>
    );
  }
  if (tab !== "digest" && !hasRawData) {
    return (
      <p
        data-testid={`raw-${tab}-unavailable`}
        className="rounded-md border border-dashed border-[var(--color-border)] bg-[var(--color-card)]/40 px-4 py-3 text-sm text-[var(--color-muted-foreground)]"
      >
        Raw Kubecost data is not exposed via the API yet. The full digest tab
        shows everything the LLM was given.
      </p>
    );
  }
  if (tab === "digest" && !hasDigest) {
    return (
      <p className="rounded-md border border-dashed border-[var(--color-border)] bg-[var(--color-card)]/40 px-4 py-3 text-sm text-[var(--color-muted-foreground)]">
        Digest unavailable for this scan.
      </p>
    );
  }
  return (
    <pre
      data-testid={`raw-${tab}-pre`}
      className="max-h-[60vh] overflow-auto rounded-md border border-[var(--color-border)] bg-[var(--color-background)] p-4 font-mono text-xs leading-relaxed text-[var(--color-foreground)]/90"
    >
      {formatted}
    </pre>
  );
}

function stringifyForTab(
  tab: TabKey,
  ctx: { digest: Digest | null; rawData: RawData | null | undefined; truncated: boolean },
): string {
  if (tab === "digest") {
    return ctx.digest ? JSON.stringify(ctx.digest, null, 2) : "";
  }
  if (ctx.truncated || ctx.rawData == null) return "";
  const slice =
    tab === "allocation"
      ? ctx.rawData.allocation
      : tab === "assets"
        ? ctx.rawData.assets
        : ctx.rawData.savings;
  if (slice === undefined) return "";
  return JSON.stringify(slice, null, 2);
}
