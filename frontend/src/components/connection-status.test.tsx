import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectionStatus, STALE_CONNECTION_THRESHOLD_MS } from "./connection-status";

const NOW = new Date("2026-05-20T12:00:00Z").getTime();

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

function dotStatus(): string | null {
  return document.querySelector("[data-status]")?.getAttribute("data-status") ?? null;
}

describe("ConnectionStatus", () => {
  it("renders ok when the check is recent and ok=true", () => {
    const oneHourAgo = new Date(NOW - 60 * 60 * 1000).toISOString();
    render(<ConnectionStatus ok lastChecked={oneHourAgo} />);
    expect(dotStatus()).toBe("ok");
    expect(screen.getByText(/checked/)).toBeInTheDocument();
    expect(screen.queryByText(/stale/)).not.toBeInTheDocument();
  });

  it("renders stale (amber) when the check is older than 24h but ok=true", () => {
    const twentyFiveHoursAgo = new Date(
      NOW - (STALE_CONNECTION_THRESHOLD_MS + 60 * 60 * 1000),
    ).toISOString();
    render(<ConnectionStatus ok lastChecked={twentyFiveHoursAgo} />);
    expect(dotStatus()).toBe("stale");
    expect(screen.getByText(/stale/)).toBeInTheDocument();
  });

  it("renders error (red) when ok=false regardless of recency", () => {
    const oneHourAgo = new Date(NOW - 60 * 60 * 1000).toISOString();
    render(
      <ConnectionStatus
        ok={false}
        lastChecked={oneHourAgo}
        error="DNS lookup failed"
      />,
    );
    expect(dotStatus()).toBe("error");
    expect(screen.getByText(/failed/)).toBeInTheDocument();
  });

  it("renders unknown (muted) when lastChecked is null", () => {
    render(<ConnectionStatus ok lastChecked={null} />);
    expect(dotStatus()).toBe("unknown");
    expect(screen.getByText("unknown")).toBeInTheDocument();
  });
});
