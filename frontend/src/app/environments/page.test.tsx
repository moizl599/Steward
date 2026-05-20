import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, type Environment } from "@/lib/api";
import { renderWithQuery } from "@/test-utils";

import EnvironmentsListPage from "./page";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

const toastMessage = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    message: (...args: unknown[]) => toastMessage(...args),
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
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
  created_at: "2026-04-30T17:49:00Z",
  updated_at: "2026-04-30T17:49:00Z",
  latest_scan: {
    id: 3,
    status: "completed",
    window: "24h",
    total_cost_usd: 0.02,
    started_at: "2026-04-30T17:54:20Z",
    completed_at: "2026-04-30T17:57:13Z",
    created_at: "2026-04-30T17:54:19Z",
  },
};

beforeEach(() => {
  push.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("EnvironmentsListPage", () => {
  it("renders a table row per environment with cluster, region and cost", async () => {
    vi.spyOn(api, "listEnvironments").mockResolvedValue([env]);
    renderWithQuery(<EnvironmentsListPage />);

    expect(await screen.findByText("kubecost-test (eks)")).toBeInTheDocument();
    expect(screen.getByText("kubecost-test")).toBeInTheDocument();
    expect(screen.getByText("us-east-1")).toBeInTheDocument();
    expect(screen.getByText("$0.02")).toBeInTheDocument();
  });

  it("renders the empty panel when no environments exist", async () => {
    vi.spyOn(api, "listEnvironments").mockResolvedValue([]);
    renderWithQuery(<EnvironmentsListPage />);
    expect(await screen.findByText(/No environments yet/)).toBeInTheDocument();
  });

  it("clicking the row navigates to the latest scan", async () => {
    vi.spyOn(api, "listEnvironments").mockResolvedValue([env]);
    const user = userEvent.setup();
    renderWithQuery(<EnvironmentsListPage />);
    const row = await screen.findByTestId("env-row-1");
    await user.click(row);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/scans/3"));
  });

  it("only renders the Scan action — Edit/Delete stubs are hidden until write flows land", async () => {
    vi.spyOn(api, "listEnvironments").mockResolvedValue([env]);
    renderWithQuery(<EnvironmentsListPage />);
    expect(await screen.findByLabelText(`Scan ${env.name}`)).toBeInTheDocument();
    expect(screen.queryByLabelText(`Edit ${env.name}`)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(`Delete ${env.name}`)).not.toBeInTheDocument();
  });

  it("toggles sort direction when the same column header is clicked twice", async () => {
    const a: Environment = { ...env, id: 1, name: "alpha" };
    const b: Environment = { ...env, id: 2, name: "beta" };
    vi.spyOn(api, "listEnvironments").mockResolvedValue([a, b]);
    const user = userEvent.setup();
    renderWithQuery(<EnvironmentsListPage />);

    const nameHead = await screen.findByRole("button", { name: /^Name/ });
    // Click twice: 1st sets desc, 2nd flips to asc.
    await user.click(nameHead);
    await user.click(nameHead);
    const rows = screen.getAllByRole("row").slice(1); // drop header
    expect(rows[0]).toHaveTextContent("alpha");
    expect(rows[1]).toHaveTextContent("beta");
  });
});
