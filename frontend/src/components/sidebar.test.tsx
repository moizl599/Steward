import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api, type Environment } from "@/lib/api";
import { renderWithQuery } from "@/test-utils";

import { Sidebar } from "./sidebar";

const baseEnv: Environment = {
  id: 1,
  name: "prod",
  kubecost_url: "http://kc",
  aws_region: "us-east-1",
  cluster_name: "prod",
  last_connection_check: new Date().toISOString(),
  last_connection_ok: true,
  last_connection_error: null,
  created_at: "2026-04-30T17:00:00Z",
  updated_at: "2026-04-30T17:00:00Z",
  latest_scan: null,
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Sidebar", () => {
  it("does not render the active-scan dot when no scans are queued or running", async () => {
    vi.spyOn(api, "listEnvironments").mockResolvedValue([
      {
        ...baseEnv,
        latest_scan: {
          id: 1,
          status: "completed",
          window: "24h",
          total_cost_usd: 1.5,
          started_at: null,
          completed_at: null,
          created_at: "2026-04-30T17:00:00Z",
        },
      },
    ]);
    renderWithQuery(<Sidebar />);
    await screen.findByText("Reports");
    expect(screen.queryByTestId("sidebar-active-scans")).not.toBeInTheDocument();
  });

  it("renders an amber dot with the count when scans are queued or running", async () => {
    vi.spyOn(api, "listEnvironments").mockResolvedValue([
      {
        ...baseEnv,
        id: 1,
        latest_scan: {
          id: 1,
          status: "running",
          window: "24h",
          total_cost_usd: null,
          started_at: null,
          completed_at: null,
          created_at: "2026-04-30T17:00:00Z",
        },
      },
      {
        ...baseEnv,
        id: 2,
        latest_scan: {
          id: 2,
          status: "queued",
          window: "24h",
          total_cost_usd: null,
          started_at: null,
          completed_at: null,
          created_at: "2026-04-30T17:00:00Z",
        },
      },
      {
        ...baseEnv,
        id: 3,
        latest_scan: {
          id: 3,
          status: "completed",
          window: "24h",
          total_cost_usd: 1.5,
          started_at: null,
          completed_at: null,
          created_at: "2026-04-30T17:00:00Z",
        },
      },
    ]);
    renderWithQuery(<Sidebar />);
    const badge = await waitFor(() => screen.getByTestId("sidebar-active-scans"));
    expect(badge).toHaveTextContent("2");
    expect(badge).toHaveAccessibleName(/2 scans in progress/i);
  });
});
