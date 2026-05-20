import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ScanFooter } from "./scan-footer";

describe("ScanFooter", () => {
  it("renders model + formatted duration + token counts when all populated", () => {
    render(
      <ScanFooter
        modelUsed="qwen2.5:7b-instruct"
        durationMs={11_400}
        promptTokens={2_481}
        completionTokens={612}
      />,
    );
    const footer = screen.getByTestId("scan-footer");
    expect(footer).toHaveTextContent("qwen2.5:7b-instruct");
    expect(footer).toHaveTextContent("11.4s");
    expect(footer).toHaveTextContent("2,481");
    expect(footer).toHaveTextContent("612");
    expect(footer.textContent ?? "").not.toContain("—");
  });

  it("falls back to em-dashes when all observability metrics are null", () => {
    render(<ScanFooter modelUsed="qwen2.5:7b-instruct" />);
    const footer = screen.getByTestId("scan-footer");
    expect(footer).toHaveTextContent("qwen2.5:7b-instruct");
    // Three em-dashes: duration + prompt + completion.
    expect(footer.textContent?.match(/—/g)?.length).toBe(3);
  });

  it("renders a mix when only some metrics are populated", () => {
    render(
      <ScanFooter
        modelUsed="qwen2.5:7b-instruct"
        durationMs={2_500}
        promptTokens={null}
        completionTokens={null}
      />,
    );
    const footer = screen.getByTestId("scan-footer");
    expect(footer).toHaveTextContent("2.5s");
    // Two em-dashes (the two token slots) when only duration is set.
    expect(footer.textContent?.match(/—/g)?.length).toBe(2);
  });

  it("renders model even when observability metrics are not provided", () => {
    render(<ScanFooter modelUsed="custom/model:7b" />);
    expect(screen.getByTestId("scan-footer")).toHaveTextContent(
      "custom/model:7b",
    );
  });
});
