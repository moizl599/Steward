import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, type Environment, type ScanWithEnv } from "@/lib/api";
import { renderWithQuery } from "@/test-utils";

import ReportsPage from "./page";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

// Recharts uses ResponsiveContainer + matchMedia; jsdom needs both stubbed.
vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ width: 400, height: 200 }}>{children}</div>
    ),
  };
});

const env: Environment = {
  id: 1,
  name: "kubecost-test",
  kubecost_url: "http://kc",
  aws_region: "us-east-1",
  cluster_name: null,
  last_connection_check: null,
  last_connection_ok: false,
  last_connection_error: null,
  created_at: "2026-04-30T17:00:00Z",
  updated_at: "2026-04-30T17:00:00Z",
  latest_scan: null,
};

const oneScan: ScanWithEnv = {
  id: 3,
  environment_id: 1,
  status: "completed",
  progress_message: null,
  error_message: null,
  window: "24h",
  total_cost_usd: 0.02,
  started_at: "2026-04-30T17:54:20Z",
  completed_at: "2026-04-30T17:57:13Z",
  created_at: "2026-04-30T17:54:19Z",
  environment_name: "kubecost-test",
  finding_count: 2,
};

const secondScan: ScanWithEnv = {
  ...oneScan,
  id: 4,
  total_cost_usd: 0.05,
  created_at: "2026-04-30T18:00:00Z",
  completed_at: "2026-04-30T18:03:00Z",
  finding_count: 3,
};

beforeEach(() => {
  push.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ReportsPage", () => {
  it("renders a table row per scan and chart placeholder when <2 completed", async () => {
    vi.spyOn(api, "listEnvironments").mockResolvedValue([env]);
    vi.spyOn(api, "listAllScans").mockResolvedValue([oneScan]);
    renderWithQuery(<ReportsPage />);

    expect(await screen.findByTestId(`scan-row-${oneScan.id}`)).toBeInTheDocument();
    expect(screen.getByText("kubecost-test")).toBeInTheDocument();
    expect(screen.getByText("$0.02")).toBeInTheDocument();
    // Trend placeholder (one completed scan, need 2).
    expect(screen.getByTestId("trend-placeholder")).toHaveTextContent(/at least 2/i);
  });

  it("renders the chart when 2+ completed scans are present", async () => {
    vi.spyOn(api, "listEnvironments").mockResolvedValue([env]);
    vi.spyOn(api, "listAllScans").mockResolvedValue([oneScan, secondScan]);
    renderWithQuery(<ReportsPage />);

    expect(await screen.findByTestId("trend-chart")).toBeInTheDocument();
    expect(screen.queryByTestId("trend-placeholder")).toBeNull();
  });

  it("changing the status filter re-queries with the new status", async () => {
    vi.spyOn(api, "listEnvironments").mockResolvedValue([env]);
    const listSpy = vi.spyOn(api, "listAllScans").mockResolvedValue([oneScan]);
    const user = userEvent.setup();
    renderWithQuery(<ReportsPage />);

    await screen.findByTestId(`scan-row-${oneScan.id}`);
    const initialCalls = listSpy.mock.calls.length;

    const statusTrigger = screen.getByTestId("filter-status");
    await user.click(statusTrigger);
    const failedOpt = await screen.findByRole("option", { name: /failed/i });
    await user.click(failedOpt);

    await waitFor(() =>
      expect(listSpy.mock.calls.length).toBeGreaterThan(initialCalls),
    );
    const last = listSpy.mock.calls.at(-1);
    expect(last?.[0]).toMatchObject({ status: "failed" });
  });

  it("typing into the from-date filter re-queries with the new from value", async () => {
    vi.spyOn(api, "listEnvironments").mockResolvedValue([env]);
    const listSpy = vi.spyOn(api, "listAllScans").mockResolvedValue([oneScan]);
    const user = userEvent.setup();
    renderWithQuery(<ReportsPage />);

    await screen.findByTestId(`scan-row-${oneScan.id}`);
    const before = listSpy.mock.calls.length;

    const fromInput = screen.getByTestId("filter-from");
    await user.type(fromInput, "2026-04-01");

    await waitFor(() => expect(listSpy.mock.calls.length).toBeGreaterThan(before));
    const last = listSpy.mock.calls.at(-1);
    expect(last?.[0]?.from).toBe("2026-04-01");
  });

  it("clicking a row navigates to the scan detail", async () => {
    vi.spyOn(api, "listEnvironments").mockResolvedValue([env]);
    vi.spyOn(api, "listAllScans").mockResolvedValue([oneScan]);
    const user = userEvent.setup();
    renderWithQuery(<ReportsPage />);

    const row = await screen.findByTestId(`scan-row-${oneScan.id}`);
    await user.click(row);
    expect(push).toHaveBeenCalledWith(`/scans/${oneScan.id}`);
  });
});
