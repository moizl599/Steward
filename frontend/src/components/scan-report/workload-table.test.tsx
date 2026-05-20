import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  mediocreSmallDigest,
  trivialCriticalDigest,
} from "@/lib/test-fixtures/digest";

import {
  IdleWorkloadsTable,
  OverProvisionedTable,
  PvcWasteTable,
  UtilCell,
  formatBytes,
} from "./workload-table";

describe("IdleWorkloadsTable", () => {
  it("renders one row per workload from the trivial fixture", () => {
    render(
      <IdleWorkloadsTable rows={trivialCriticalDigest.idle_workloads} />,
    );
    for (const w of trivialCriticalDigest.idle_workloads) {
      expect(
        screen.getByTestId(`idle-row-${w.name}`),
      ).toBeInTheDocument();
    }
    expect(screen.getByText(/CPU < 5% · Memory < 10%/)).toBeInTheDocument();
  });

  it("sorts rows by impact descending then name ascending", () => {
    const a = {
      ...trivialCriticalDigest.idle_workloads[0],
      name: "ns/Deployment/aaa",
      impact_usd: 5,
    };
    const b = {
      ...trivialCriticalDigest.idle_workloads[0],
      name: "ns/Deployment/bbb",
      impact_usd: 5,
    };
    const c = {
      ...trivialCriticalDigest.idle_workloads[0],
      name: "ns/Deployment/ccc",
      impact_usd: 12,
    };
    render(<IdleWorkloadsTable rows={[a, b, c]} />);
    const rows = screen.getAllByTestId(/^idle-row-/);
    expect(rows[0]).toHaveAttribute(
      "data-testid",
      "idle-row-ns/Deployment/ccc",
    );
    expect(rows[1]).toHaveAttribute(
      "data-testid",
      "idle-row-ns/Deployment/aaa",
    );
    expect(rows[2]).toHaveAttribute(
      "data-testid",
      "idle-row-ns/Deployment/bbb",
    );
  });

  it("renders empty state when there are no idle workloads", () => {
    render(<IdleWorkloadsTable rows={[]} />);
    expect(screen.getByTestId("section-idle-empty")).toHaveTextContent(
      /No idle workloads/,
    );
  });

  it("truncates long workload names but keeps the full name in title", () => {
    const long = "a".repeat(60);
    render(
      <IdleWorkloadsTable
        rows={[
          {
            ...trivialCriticalDigest.idle_workloads[0],
            name: long,
          },
        ]}
      />,
    );
    const row = screen.getByTestId(`idle-row-${long}`);
    const cell = within(row).getByTitle(long);
    expect(cell.textContent).toMatch(/…$/);
    expect(cell.textContent!.length).toBeLessThanOrEqual(40);
  });

  it("renders ImpactCell as em-dash when impact is zero", () => {
    const row = {
      ...trivialCriticalDigest.idle_workloads[0],
      impact_usd: 0,
    };
    render(<IdleWorkloadsTable rows={[row]} />);
    const tr = screen.getByTestId(`idle-row-${row.name}`);
    expect(within(tr).getByText("—")).toBeInTheDocument();
  });
});

describe("OverProvisionedTable", () => {
  it("uses the over-provisioned threshold subtitle", () => {
    render(
      <OverProvisionedTable rows={mediocreSmallDigest.over_provisioned} />,
    );
    expect(screen.getByText(/Request > 4× usage · cost > \$20/)).toBeInTheDocument();
  });

  it("renders empty state when no over-prov workloads", () => {
    render(<OverProvisionedTable rows={[]} />);
    expect(screen.getByTestId("section-over-prov-empty")).toHaveTextContent(
      /No over-provisioned workloads/,
    );
  });
});

describe("PvcWasteTable", () => {
  it("formats provisioned / used bytes", () => {
    render(<PvcWasteTable rows={mediocreSmallDigest.pvc_waste} />);
    // 100 GB and 8 GB after rounding.
    expect(screen.getByText(/93\.1 GB|100 GB/)).toBeInTheDocument();
    expect(screen.getByText(/7\.5 GB|8 GB/)).toBeInTheDocument();
  });

  it("renders empty state when no PVC waste", () => {
    render(<PvcWasteTable rows={[]} />);
    expect(screen.getByTestId("section-pvc-waste-empty")).toHaveTextContent(
      /No PVC waste/,
    );
  });
});

describe("UtilCell colours", () => {
  it("colours <5% with destructive token", () => {
    const { container } = render(<UtilCell value={0.02} />);
    const bar = container.querySelector("div > div > div > div");
    expect(bar?.className).toContain("var(--color-destructive)");
  });

  it("colours 5-20% with warn token", () => {
    const { container } = render(<UtilCell value={0.12} />);
    const bar = container.querySelector("div > div > div > div");
    expect(bar?.className).toContain("var(--color-warn)");
  });

  it("colours >20% with muted-foreground token", () => {
    const { container } = render(<UtilCell value={0.45} />);
    const bar = container.querySelector("div > div > div > div");
    expect(bar?.className).toContain("var(--color-muted-foreground)");
  });
});

describe("formatBytes", () => {
  it("falls back to bytes for small values", () => {
    expect(formatBytes(512)).toBe("512 B");
  });
  it("rounds to one decimal for KB and up", () => {
    expect(formatBytes(2_500)).toBe("2.4 KB");
    expect(formatBytes(8 * 1024 * 1024 * 1024)).toBe("8.0 GB");
  });
  it("returns 0 B for non-positive input", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(-5)).toBe("0 B");
  });
});
