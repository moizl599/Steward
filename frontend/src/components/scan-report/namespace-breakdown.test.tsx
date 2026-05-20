import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Digest } from "@/lib/digest";
import {
  healthyProductionDigest,
  trivialCriticalDigest,
} from "@/lib/test-fixtures/digest";

import { NamespaceBreakdown } from "./namespace-breakdown";

describe("NamespaceBreakdown — trivial fixture", () => {
  it("renders a segment + legend entry per namespace", () => {
    render(<NamespaceBreakdown digest={trivialCriticalDigest} />);
    for (const ns of trivialCriticalDigest.top_namespaces_by_cost) {
      expect(screen.getByText(ns.namespace)).toBeInTheDocument();
    }
    expect(screen.getByTestId("ns-segment-0")).toHaveStyle({
      background: "var(--color-info)",
    });
    // Sub-label is e.g. "$1.47 total · 4 namespaces".
    expect(screen.getByText(/4 namespaces/)).toBeInTheDocument();
  });
});

describe("NamespaceBreakdown — healthy fixture", () => {
  it("renders the production-scale namespace mix", () => {
    render(<NamespaceBreakdown digest={healthyProductionDigest} />);
    expect(screen.getByText("production-api")).toBeInTheDocument();
    expect(screen.getByText("data-platform")).toBeInTheDocument();
    expect(screen.getByText(/4 namespaces/)).toBeInTheDocument();
  });
});

describe("NamespaceBreakdown — edge cases", () => {
  it("renders an empty-state when top_namespaces_by_cost is empty", () => {
    const digest: Digest = {
      ...trivialCriticalDigest,
      top_namespaces_by_cost: [],
    };
    render(<NamespaceBreakdown digest={digest} />);
    expect(
      screen.getByText("No allocation data in this scan."),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("ns-bar")).toBeNull();
  });

  it("collapses tail into a single Other segment once >9 namespaces", () => {
    const long = Array.from({ length: 14 }, (_, i) => ({
      namespace: `ns-${i}`,
      cost_usd: 10 + i,
      share: 1 / 14,
    }));
    const digest: Digest = {
      ...trivialCriticalDigest,
      top_namespaces_by_cost: long,
    };
    render(<NamespaceBreakdown digest={digest} />);
    // First 9 individual + 1 Other == 10 segments.
    expect(screen.getByTestId("ns-segment-9")).toBeInTheDocument();
    expect(screen.queryByTestId("ns-segment-10")).toBeNull();
    expect(
      screen.getByText("Other (5 namespaces)"),
    ).toBeInTheDocument();
  });

  it("singular noun when exactly one namespace", () => {
    const digest: Digest = {
      ...trivialCriticalDigest,
      top_namespaces_by_cost: [
        { namespace: "only", cost_usd: 5, share: 1 },
      ],
    };
    render(<NamespaceBreakdown digest={digest} />);
    expect(screen.getByText(/1 namespace$/)).toBeInTheDocument();
  });
});
