import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Finding } from "@/lib/api";

import { FindingCard, sortFindings } from "./finding-card";

const base: Finding = {
  title: "Idle deployment",
  severity: "critical",
  category: "idle_workloads",
  recommendation: "Delete the deployment.",
  impact_usd: 32.65,
  affected_resource: "default/Deployment/redis",
  rationale: "Sat at 0% CPU for the full window.",
};

describe("FindingCard — severity to left border", () => {
  it("renders a destructive left border for critical", () => {
    render(
      <ul>
        <FindingCard finding={base} />
      </ul>,
    );
    const li = screen.getByTestId("finding-row");
    expect(li).toHaveAttribute("data-severity", "critical");
    expect(li.className).toContain("border-l-[var(--color-destructive)]");
  });

  it("renders a warn left border for medium", () => {
    render(
      <ul>
        <FindingCard finding={{ ...base, severity: "medium" }} />
      </ul>,
    );
    expect(screen.getByTestId("finding-row").className).toContain(
      "border-l-[var(--color-warn)]",
    );
  });

  it("renders no left border for info", () => {
    render(
      <ul>
        <FindingCard finding={{ ...base, severity: "info" }} />
      </ul>,
    );
    expect(screen.getByTestId("finding-row").className).not.toContain(
      "border-l-[3px]",
    );
  });
});

describe("FindingCard — impact + rationale toggle", () => {
  it("renders the impact value when present", () => {
    render(
      <ul>
        <FindingCard finding={base} />
      </ul>,
    );
    expect(screen.getByTestId("finding-impact")).toHaveTextContent("$32.65");
  });

  it("hides the impact when impact_usd is null", () => {
    render(
      <ul>
        <FindingCard finding={{ ...base, impact_usd: null }} />
      </ul>,
    );
    expect(screen.queryByTestId("finding-impact")).toBeNull();
  });

  it("hides category dot when affected_resource is null", () => {
    render(
      <ul>
        <FindingCard finding={{ ...base, affected_resource: null }} />
      </ul>,
    );
    // Category eyebrow still renders; affected_resource pill does not.
    expect(
      screen.getByText((content) => content.trim() === "idle_workloads"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("finding-affected-resource")).toBeNull();
  });

  it("renders affected_resource as a mono pill preserving K8s case", () => {
    render(
      <ul>
        <FindingCard
          finding={{
            ...base,
            affected_resource: "default/Deployment/Nginx-API",
          }}
        />
      </ul>,
    );
    const pill = screen.getByTestId("finding-affected-resource");
    // The pill must not inherit uppercase from the category eyebrow — K8s
    // names are case-sensitive.
    expect(pill).toHaveTextContent("default/Deployment/Nginx-API");
    expect(pill.className).not.toContain("uppercase");
    // Pill has its own border to look like a structured chip, not appended
    // prose.
    expect(pill.className).toContain("border");
  });

  it("toggles the rationale block when present", async () => {
    const user = userEvent.setup();
    render(
      <ul>
        <FindingCard finding={base} />
      </ul>,
    );
    expect(screen.queryByTestId("finding-rationale")).toBeNull();
    await user.click(screen.getByTestId("finding-rationale-toggle"));
    expect(screen.getByTestId("finding-rationale")).toHaveTextContent(
      /Sat at 0% CPU/,
    );
  });

  it("does not render the rationale toggle when rationale is null", () => {
    render(
      <ul>
        <FindingCard finding={{ ...base, rationale: null }} />
      </ul>,
    );
    expect(screen.queryByTestId("finding-rationale-toggle")).toBeNull();
  });
});

describe("FindingCard — healthy variant", () => {
  it("renders the small healthy card for info + healthyVariant", () => {
    render(
      <ul>
        <FindingCard
          finding={{
            ...base,
            severity: "info",
            title: "Cluster looks fine.",
            rationale: null,
            impact_usd: null,
          }}
          healthyVariant
        />
      </ul>,
    );
    const card = screen.getByTestId("finding-row");
    expect(card).toHaveAttribute("data-variant", "healthy");
    expect(card).toHaveTextContent("Cluster looks fine.");
  });

  it("falls through to the full card for non-info even with healthyVariant", () => {
    render(
      <ul>
        <FindingCard finding={base} healthyVariant />
      </ul>,
    );
    expect(screen.getByTestId("finding-row")).toHaveAttribute(
      "data-severity",
      "critical",
    );
  });
});

describe("sortFindings", () => {
  it("orders by severity then impact descending", () => {
    const findings: Finding[] = [
      { ...base, severity: "low", impact_usd: 50 },
      { ...base, severity: "critical", impact_usd: 5 },
      { ...base, severity: "high", impact_usd: 200 },
      { ...base, severity: "high", impact_usd: 100 },
      { ...base, severity: "info", impact_usd: null },
    ];
    const sorted = sortFindings(findings);
    expect(sorted.map((f) => f.severity)).toEqual([
      "critical",
      "high",
      "high",
      "low",
      "info",
    ]);
    expect(sorted[1].impact_usd).toBe(200);
    expect(sorted[2].impact_usd).toBe(100);
  });
});
