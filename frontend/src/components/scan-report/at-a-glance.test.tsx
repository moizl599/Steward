import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { gradeFromRatio } from "@/lib/digest";
import {
  healthyProductionDigest,
  mediocreSmallDigest,
  trivialCriticalDigest,
} from "@/lib/test-fixtures/digest";

import { AtAGlance, EfficiencyDial, GradeChip, ScalePill } from "./at-a-glance";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AtAGlance — trivial/critical (scan #4 fixture)", () => {
  it("renders scale label, run-rate, and trivial-tinted pill", () => {
    render(<AtAGlance digest={trivialCriticalDigest} />);
    // The scale label appears twice: as the H3 big label and inside the pill.
    const trivials = screen.getAllByText(/^Trivial$/);
    expect(trivials.length).toBe(2);
    expect(screen.getByText("lab / dev cluster")).toBeInTheDocument();
    expect(screen.getByText(/\$44\.24/)).toBeInTheDocument();
    // At least one match (the pill) carries the destructive token.
    expect(
      trivials.some((el) =>
        el.className.includes("var(--color-destructive)"),
      ),
    ).toBe(true);
  });

  it("renders three dials with the digest's efficiency values", () => {
    render(<AtAGlance digest={trivialCriticalDigest} />);
    expect(screen.getByTestId("dial-cpu-value")).toHaveTextContent("3.5%");
    expect(screen.getByTestId("dial-memory-value")).toHaveTextContent("47.5%");
    expect(screen.getByTestId("dial-overall-value")).toHaveTextContent("8.3%");
    expect(screen.getByText("Critical")).toBeInTheDocument();
  });

  it("renders signal counts; non-zero numbers use severity colours", () => {
    render(<AtAGlance digest={trivialCriticalDigest} />);
    const idle = screen.getByTestId("signal-idle");
    expect(idle).toHaveAttribute("data-interactive", "true");
    expect(idle).toHaveTextContent("3");
    // Idle has 3 entries → destructive colour token in class.
    expect(idle.querySelector("span")?.className).toContain(
      "var(--color-destructive)",
    );
    // Anomalies has no table → non-interactive.
    expect(screen.getByTestId("signal-anomalies")).toHaveAttribute(
      "data-interactive",
      "false",
    );
  });

  it("signal buttons trigger scrollIntoView on the right section", async () => {
    const target = document.createElement("div");
    target.id = "idle";
    document.body.appendChild(target);
    const spy = vi.spyOn(target, "scrollIntoView").mockImplementation(() => {});

    const user = userEvent.setup();
    render(<AtAGlance digest={trivialCriticalDigest} />);
    await user.click(screen.getByTestId("signal-idle"));
    expect(spy).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });

    document.body.removeChild(target);
  });
});

describe("AtAGlance — healthy/production", () => {
  it("renders production scale pill and healthy chip", () => {
    render(<AtAGlance digest={healthyProductionDigest} />);
    expect(screen.getAllByText("Production").length).toBe(2); // H3 + pill
    expect(screen.getByText("Healthy")).toBeInTheDocument();
    expect(screen.getByText("production workload")).toBeInTheDocument();
  });

  it("renders all signal counts in muted colour when every count is zero", () => {
    render(<AtAGlance digest={healthyProductionDigest} />);
    for (const id of [
      "signal-idle",
      "signal-overprov",
      "signal-pvc",
      "signal-anomalies",
    ]) {
      const cell = screen.getByTestId(id);
      expect(cell).toHaveTextContent("0");
      expect(cell.querySelector("span")?.className).toContain(
        "var(--color-muted-foreground)",
      );
    }
  });
});

describe("AtAGlance — mediocre/small", () => {
  it("renders mediocre grade chip and small scale", () => {
    render(<AtAGlance digest={mediocreSmallDigest} />);
    expect(screen.getAllByText("Small").length).toBe(2); // H3 + pill
    expect(screen.getByText("Mediocre")).toBeInTheDocument();
    expect(screen.getByText("small workload")).toBeInTheDocument();
  });
});

describe("EfficiencyDial", () => {
  it("uses the savings token when value lands healthy", () => {
    const { container } = render(<EfficiencyDial value={0.62} label="Overall" />);
    const arc = container.querySelectorAll("circle")[1];
    expect(arc).toHaveAttribute("stroke", "var(--color-savings)");
  });

  it("uses the destructive token when value lands critical", () => {
    const { container } = render(<EfficiencyDial value={0.08} label="CPU" />);
    const arc = container.querySelectorAll("circle")[1];
    expect(arc).toHaveAttribute("stroke", "var(--color-destructive)");
  });

  it("clamps values above 100% so the arc never overdraws", () => {
    const { container } = render(<EfficiencyDial value={1.4} label="Overall" />);
    const arc = container.querySelectorAll("circle")[1];
    const dasharray = arc.getAttribute("stroke-dasharray") ?? "";
    const [filled] = dasharray.split(" ").map(Number);
    const circumference = 2 * Math.PI * 22;
    expect(filled).toBeLessThanOrEqual(circumference + 0.001);
  });

  it("colours each dial independently of the overall grade", () => {
    const { container } = render(<EfficiencyDial value={0.6} label="Memory" />);
    const arc = container.querySelectorAll("circle")[1];
    // Memory at 60% is healthy by the same bucket logic, regardless of
    // whether the overall grade was critical.
    expect(arc).toHaveAttribute("stroke", "var(--color-savings)");
  });
});

describe("ScalePill", () => {
  it("renders the canonical label for each scale", () => {
    const { rerender } = render(<ScalePill scale="trivial" />);
    expect(screen.getByText("Trivial")).toBeInTheDocument();
    rerender(<ScalePill scale="small" />);
    expect(screen.getByText("Small")).toBeInTheDocument();
    rerender(<ScalePill scale="production" />);
    expect(screen.getByText("Production")).toBeInTheDocument();
  });
});

describe("GradeChip", () => {
  it("renders the canonical label for each grade", () => {
    const { rerender } = render(<GradeChip grade="healthy" />);
    expect(screen.getByText("Healthy")).toBeInTheDocument();
    rerender(<GradeChip grade="mediocre" />);
    expect(screen.getByText("Mediocre")).toBeInTheDocument();
    rerender(<GradeChip grade="poor" />);
    expect(screen.getByText("Poor")).toBeInTheDocument();
    rerender(<GradeChip grade="critical" />);
    expect(screen.getByText("Critical")).toBeInTheDocument();
  });
});

describe("gradeFromRatio", () => {
  it("buckets the canonical edge values", () => {
    expect(gradeFromRatio(0.5)).toBe("healthy");
    expect(gradeFromRatio(0.49)).toBe("mediocre");
    expect(gradeFromRatio(0.3)).toBe("mediocre");
    expect(gradeFromRatio(0.29)).toBe("poor");
    expect(gradeFromRatio(0.15)).toBe("poor");
    expect(gradeFromRatio(0.14)).toBe("critical");
  });
});
