import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import { renderWithQuery } from "@/test-utils";

import NewEnvironmentPage from "./page";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

beforeEach(() => {
  push.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

const fillRequired = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.type(screen.getByLabelText(/^Name$/), "kubecost-test (eks)");
  await user.type(
    screen.getByLabelText(/Kubecost URL/),
    "http://kubecost.example.com:9090",
  );
};

describe("NewEnvironmentPage", () => {
  it("submits, runs test-connection, and navigates home on success", async () => {
    vi.spyOn(api, "createEnvironment").mockResolvedValue({
      id: 7,
      name: "kubecost-test (eks)",
      kubecost_url: "http://kubecost.example.com:9090",
      aws_region: "us-east-1",
      cluster_name: null,
      last_connection_check: null,
      last_connection_ok: false,
      last_connection_error: null,
      created_at: "now",
      updated_at: "now",
      latest_scan: null,
    });
    vi.spyOn(api, "testConnection").mockResolvedValue({
      ok: true,
      message: "Connected",
      kubecost_version: "1.34",
      latency_ms: 521,
    });

    const user = userEvent.setup();
    renderWithQuery(<NewEnvironmentPage />);
    await fillRequired(user);
    await user.click(screen.getByRole("button", { name: /add environment/i }));

    expect(await screen.findByTestId("connection-result")).toHaveTextContent(
      /Connected — Kubecost 1\.34/i,
    );
    expect(api.createEnvironment).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "kubecost-test (eks)",
        kubecost_url: "http://kubecost.example.com:9090",
        aws_region: "us-east-1",
      }),
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith("/"), { timeout: 2000 });
  });

  it("renders inline validation errors when the user submits an invalid URL", async () => {
    const user = userEvent.setup();
    renderWithQuery(<NewEnvironmentPage />);
    await user.type(screen.getByLabelText(/^Name$/), "nope");
    await user.type(screen.getByLabelText(/Kubecost URL/), "not-a-url");
    await user.click(screen.getByRole("button", { name: /add environment/i }));
    expect(await screen.findByText(/Must be a valid URL/i)).toBeInTheDocument();
  });

  it("surfaces server (5xx) errors as a banner above the form", async () => {
    vi.spyOn(api, "createEnvironment").mockRejectedValue(
      new ApiError(500, { detail: "boom" }, "boom"),
    );

    const user = userEvent.setup();
    renderWithQuery(<NewEnvironmentPage />);
    await fillRequired(user);
    await user.click(screen.getByRole("button", { name: /add environment/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/boom/i);
  });

  it("surfaces 4xx field errors as inline messages on the offending field", async () => {
    vi.spyOn(api, "createEnvironment").mockRejectedValue(
      new ApiError(
        422,
        {
          detail: [
            {
              loc: ["body", "kubecost_url"],
              msg: "URL must use http or https scheme",
              type: "value_error",
            },
          ],
        },
        "validation error",
      ),
    );

    const user = userEvent.setup();
    renderWithQuery(<NewEnvironmentPage />);
    await fillRequired(user);
    await user.click(screen.getByRole("button", { name: /add environment/i }));

    expect(
      await screen.findByText(/URL must use http or https scheme/i),
    ).toBeInTheDocument();
  });
});
