import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, type Environment } from "@/lib/api";
import { renderWithQuery } from "@/test-utils";

import DashboardPage, { DashboardSummary } from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

const baseEnv: Environment = {
  id: 1,
  name: "kubecost-test (eks)",
  kubecost_url: "http://kubecost.example.com",
  aws_region: "us-east-1",
  cluster_name: "kubecost-test",
  last_connection_check: new Date().toISOString(),
  last_connection_ok: true,
  last_connection_error: null,
  created_at: "2026-04-30T17:00:00Z",
  updated_at: "2026-04-30T17:00:00Z",
  latest_scan: {
    id: 3,
    status: "completed",
    window: "24h",
    total_cost_usd: 0.02,
    started_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
  },
};

beforeEach(() => {
  vi.spyOn(api, "listEnvironments").mockResolvedValue([baseEnv]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("DashboardPage", () => {
  it("renders environment cards from the API", async () => {
    renderWithQuery(<DashboardPage />);
    expect(await screen.findByText("kubecost-test (eks)")).toBeInTheDocument();
    expect(screen.getByText("us-east-1")).toBeInTheDocument();
    expect(screen.getByText("kubecost-test")).toBeInTheDocument();
    expect(screen.getByText("$0.02")).toBeInTheDocument();
  });

  it("renders the empty state when the API returns no environments", async () => {
    vi.spyOn(api, "listEnvironments").mockResolvedValue([]);
    renderWithQuery(<DashboardPage />);
    expect(await screen.findByText("No environments yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /add environment/i })).toBeInTheDocument();
  });

  it("renders skeleton placeholders while loading", async () => {
    let resolve: (envs: Environment[]) => void = () => {};
    const pending = new Promise<Environment[]>((r) => (resolve = r));
    vi.spyOn(api, "listEnvironments").mockReturnValue(pending);
    const { container } = renderWithQuery(<DashboardPage />);
    expect(container.querySelector('[data-slot="skeleton"]')).not.toBeNull();
    resolve([baseEnv]);
    await waitFor(() => {
      expect(screen.getByText("kubecost-test (eks)")).toBeInTheDocument();
    });
  });

  it("renders an error state with a retry button when the API fails", async () => {
    vi.spyOn(api, "listEnvironments").mockRejectedValue(new Error("network down"));
    renderWithQuery(<DashboardPage />);
    expect(await screen.findByText(/Couldn't load environments/i)).toBeInTheDocument();
    expect(screen.getByText(/network down/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });
});

describe("DashboardSummary", () => {
  const envWith = (
    overrides: Partial<Environment> & { latest_scan?: Environment["latest_scan"] },
  ): Environment => ({
    ...baseEnv,
    ...overrides,
  });

  it("returns null when there are no environments", () => {
    const { container } = render(<DashboardSummary envs={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("aggregates env count, total cost, finding count, and active scans", () => {
    const envs: Environment[] = [
      envWith({
        id: 1,
        latest_scan: {
          id: 10,
          status: "completed",
          window: "24h",
          total_cost_usd: 1.0,
          started_at: null,
          completed_at: null,
          created_at: "2026-04-30T17:00:00Z",
          finding_count: 2,
        },
      }),
      envWith({
        id: 2,
        latest_scan: {
          id: 11,
          status: "completed",
          window: "24h",
          total_cost_usd: 0.47,
          started_at: null,
          completed_at: null,
          created_at: "2026-04-30T17:00:00Z",
          finding_count: 1,
        },
      }),
      envWith({
        id: 3,
        latest_scan: {
          id: 12,
          status: "running",
          window: "24h",
          total_cost_usd: null,
          started_at: null,
          completed_at: null,
          created_at: "2026-04-30T17:00:00Z",
          finding_count: null,
        },
      }),
    ];
    render(<DashboardSummary envs={envs} />);
    const summary = screen.getByTestId("dashboard-summary");
    expect(summary).toHaveTextContent("3 environments");
    expect(summary).toHaveTextContent("$1.47 / 24h total");
    expect(summary).toHaveTextContent("3 open findings");
    expect(summary).toHaveTextContent("1 scan running");
  });

  it("omits the active-scans suffix when no scans are queued or running", () => {
    const envs: Environment[] = [
      envWith({
        id: 1,
        latest_scan: {
          id: 10,
          status: "completed",
          window: "24h",
          total_cost_usd: 5.0,
          started_at: null,
          completed_at: null,
          created_at: "2026-04-30T17:00:00Z",
          finding_count: 0,
        },
      }),
    ];
    render(<DashboardSummary envs={envs} />);
    expect(screen.getByTestId("dashboard-summary")).not.toHaveTextContent(/scan(s)? running/);
  });
});
