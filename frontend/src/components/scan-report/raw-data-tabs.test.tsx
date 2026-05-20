import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { trivialCriticalDigest } from "@/lib/test-fixtures/digest";

import { RawDataTabs } from "./raw-data-tabs";

describe("RawDataTabs", () => {
  it("renders all four tab triggers", () => {
    render(<RawDataTabs digest={trivialCriticalDigest} />);
    expect(screen.getByTestId("raw-tab-allocation")).toBeInTheDocument();
    expect(screen.getByTestId("raw-tab-assets")).toBeInTheDocument();
    expect(screen.getByTestId("raw-tab-savings")).toBeInTheDocument();
    expect(screen.getByTestId("raw-tab-digest")).toBeInTheDocument();
  });

  it("Full digest tab shows the stringified digest when raw_data is absent", async () => {
    const user = userEvent.setup();
    render(<RawDataTabs digest={trivialCriticalDigest} />);
    await user.click(screen.getByTestId("raw-tab-digest"));
    expect(screen.getByTestId("raw-digest-pre")).toHaveTextContent(
      /"cluster_scale": "trivial"/,
    );
  });

  it("Allocation tab without raw_data shows the unavailable placeholder", () => {
    render(<RawDataTabs digest={trivialCriticalDigest} />);
    // Allocation is the default active tab.
    expect(screen.getByTestId("raw-allocation-unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("raw-allocation-pre")).toBeNull();
  });

  it("Allocation tab with raw_data stringifies the slice", async () => {
    const user = userEvent.setup();
    const rawData = {
      allocation: { data: [{ "ns/Deployment/api": { cpuCost: 1 } }] },
      assets: null,
      savings: null,
    };
    render(<RawDataTabs digest={trivialCriticalDigest} rawData={rawData} />);
    await user.click(screen.getByTestId("raw-tab-allocation"));
    expect(screen.getByTestId("raw-allocation-pre")).toHaveTextContent(
      /"cpuCost": 1/,
    );
  });

  it("renders truncation note in raw tabs when raw_data.truncated", () => {
    render(
      <RawDataTabs
        digest={trivialCriticalDigest}
        rawData={{ truncated: true, original_bytes: 287_456 }}
      />,
    );
    expect(
      screen.getByTestId("raw-allocation-truncated"),
    ).toHaveTextContent(/287,456 bytes/);
  });

  it("Full digest tab unaffected by truncation", async () => {
    const user = userEvent.setup();
    render(
      <RawDataTabs
        digest={trivialCriticalDigest}
        rawData={{ truncated: true, original_bytes: 999_999 }}
      />,
    );
    await user.click(screen.getByTestId("raw-tab-digest"));
    expect(screen.getByTestId("raw-digest-pre")).toHaveTextContent(
      /"cluster_scale": "trivial"/,
    );
  });

  it("digest=null shows an explicit unavailable note in the digest tab", async () => {
    const user = userEvent.setup();
    render(<RawDataTabs digest={null} />);
    await user.click(screen.getByTestId("raw-tab-digest"));
    expect(
      screen.getByText("Digest unavailable for this scan."),
    ).toBeInTheDocument();
  });
});
