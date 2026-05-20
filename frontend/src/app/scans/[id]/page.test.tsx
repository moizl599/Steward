import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, type Environment, type Report, type Scan } from "@/lib/api";
import { trivialCriticalDigest } from "@/lib/test-fixtures/digest";
import { renderWithQuery } from "@/test-utils";

import ScanDetailPage from "./page";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useParams: () => ({ id: "3" }),
}));

const env: Environment = {
  id: 1,
  name: "kubecost-test (eks)",
  kubecost_url: "http://kc",
  aws_region: "us-east-1",
  cluster_name: "kubecost-test",
  last_connection_check: new Date().toISOString(),
  last_connection_ok: true,
  last_connection_error: null,
  created_at: "now",
  updated_at: "now",
  latest_scan: null,
};

const completedScan: Scan = {
  id: 3,
  environment_id: 1,
  status: "completed",
  progress_message: "Completed",
  error_message: null,
  window: "24h",
  total_cost_usd: 1.47,
  started_at: "2026-04-30T17:54:20Z",
  completed_at: "2026-04-30T17:57:13Z",
  created_at: "2026-04-30T17:54:19Z",
};

const report: Report = {
  id: 1,
  scan_id: 3,
  executive_summary:
    "This is a trivial-scale cluster (≈$44/mo run-rate) with critical efficiency issues.",
  findings: [
    {
      title: "Idle deployment",
      severity: "critical",
      category: "idle_workloads",
      impact_usd: 0.42,
      affected_resource: "kube-system/Deployment/coredns",
      recommendation: "Delete or scale-to-zero kube-system/Deployment/coredns.",
      rationale: "Sat at 0.5% CPU for the full window.",
    },
  ],
  estimated_monthly_savings_usd: 0,
  model_used: "qwen2.5:7b-instruct",
  duration_ms: 11_400,
  prompt_tokens: 2_481,
  completion_tokens: 612,
  created_at: "2026-04-30T17:57:13Z",
};

beforeEach(() => {
  push.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ScanDetailPage — completed", () => {
  it("renders header, at-a-glance row, executive summary, findings, and raw data tabs", async () => {
    vi.spyOn(api, "getScan").mockResolvedValue(completedScan);
    vi.spyOn(api, "getEnvironment").mockResolvedValue(env);
    vi.spyOn(api, "getReport").mockResolvedValue(report);
    vi.spyOn(api, "getDigest").mockResolvedValue(trivialCriticalDigest);
    vi.spyOn(api, "getRawData").mockResolvedValue(null);

    renderWithQuery(<ScanDetailPage />);

    expect(await screen.findByText(/Scan #3/)).toBeInTheDocument();
    expect(
      await screen.findByText(/kubecost-test \(eks\)/),
    ).toBeInTheDocument();
    // Hero: total cost rendered prominently (also appears in namespace
    // breakdown total, so allow multiple matches).
    expect(screen.getAllByText("$1.47").length).toBeGreaterThan(0);
    // AtAGlance: Trivial scale (H3 + glance pill + header pill) + Critical chip.
    const trivials = await screen.findAllByText("Trivial");
    expect(trivials.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Critical")).toBeInTheDocument();
    // Namespace breakdown.
    expect(screen.getByTestId("namespace-breakdown")).toBeInTheDocument();
    // Executive summary.
    expect(
      screen.getByText(/trivial-scale cluster/i),
    ).toBeInTheDocument();
    // Finding card.
    expect(screen.getByTestId("finding-row")).toHaveTextContent(
      /Idle deployment/,
    );
    // Workload tables — idle has data; over-prov/pvc empty.
    expect(screen.getByTestId("section-idle")).toBeInTheDocument();
    expect(
      screen.getByTestId("section-over-prov-empty"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("section-pvc-waste-empty")).toBeInTheDocument();
    // Raw data tabs.
    expect(screen.getByTestId("raw-data-tabs")).toBeInTheDocument();
    expect(screen.getByTestId("raw-tab-digest")).toBeInTheDocument();
    // Scan footer renders model.
    expect(screen.getByTestId("scan-footer")).toHaveTextContent(
      /qwen2\.5:7b-instruct/,
    );
  });

  it("switches to the digest tab and shows the stringified digest", async () => {
    vi.spyOn(api, "getScan").mockResolvedValue(completedScan);
    vi.spyOn(api, "getEnvironment").mockResolvedValue(env);
    vi.spyOn(api, "getReport").mockResolvedValue(report);
    vi.spyOn(api, "getDigest").mockResolvedValue(trivialCriticalDigest);
    vi.spyOn(api, "getRawData").mockResolvedValue(null);

    const user = userEvent.setup();
    renderWithQuery(<ScanDetailPage />);
    await screen.findByTestId("raw-tab-digest");
    await user.click(screen.getByTestId("raw-tab-digest"));
    expect(screen.getByTestId("raw-digest-pre")).toHaveTextContent(
      /"cluster_scale": "trivial"/,
    );
  });
});

describe("ScanDetailPage — running with polling", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls the scan endpoint while running and stops when completed", async () => {
    const getScan = vi.spyOn(api, "getScan");
    getScan
      .mockResolvedValueOnce({
        ...completedScan,
        status: "running",
        progress_message: "Building digest",
      })
      .mockResolvedValueOnce({
        ...completedScan,
        status: "running",
        progress_message: "Analyzing (model: qwen2.5:7b-instruct)",
      })
      .mockResolvedValue(completedScan);
    vi.spyOn(api, "getEnvironment").mockResolvedValue(env);
    vi.spyOn(api, "getReport").mockResolvedValue(report);
    vi.spyOn(api, "getDigest").mockResolvedValue(trivialCriticalDigest);
    vi.spyOn(api, "getRawData").mockResolvedValue(null);

    renderWithQuery(<ScanDetailPage />);

    await waitFor(() => expect(getScan).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Building digest/)).toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(2000);
    await waitFor(() => expect(getScan).toHaveBeenCalledTimes(2));

    await vi.advanceTimersByTimeAsync(2000);
    await waitFor(() => expect(getScan).toHaveBeenCalledTimes(3));

    const callCountAtTerminal = getScan.mock.calls.length;
    await vi.advanceTimersByTimeAsync(6000);
    expect(getScan).toHaveBeenCalledTimes(callCountAtTerminal);
  });
});

describe("ScanDetailPage — failed", () => {
  it("renders the error banner and a working retry button", async () => {
    const failed: Scan = {
      ...completedScan,
      status: "failed",
      error_message: "Kubecost: Prometheus unavailable",
      progress_message: "Failed",
      completed_at: null,
      total_cost_usd: null,
    };
    vi.spyOn(api, "getScan").mockResolvedValue(failed);
    vi.spyOn(api, "getEnvironment").mockResolvedValue(env);
    const trigger = vi.spyOn(api, "triggerScan").mockResolvedValue({
      ...completedScan,
      id: 99,
      status: "queued",
    });

    const user = userEvent.setup();
    renderWithQuery(<ScanDetailPage />);
    expect(
      await screen.findByTestId("scan-failed-banner"),
    ).toHaveTextContent(/Prometheus unavailable/);

    await user.click(screen.getByRole("button", { name: /retry scan/i }));
    expect(trigger).toHaveBeenCalledWith(1, "24h");
    await waitFor(() => expect(push).toHaveBeenCalledWith("/scans/99"));
  });
});
