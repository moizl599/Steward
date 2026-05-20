import { describe, expect, it } from "vitest";

import { formatUSD } from "@/lib/utils";

describe("formatUSD", () => {
  it("formats a value with standard notation and two fraction digits by default", () => {
    expect(formatUSD(1234.5)).toBe("$1,234.50");
  });

  it("rounds standard notation to two fraction digits", () => {
    expect(formatUSD(1234.567)).toBe("$1,234.57");
  });

  it("renders zero as $0.00", () => {
    expect(formatUSD(0)).toBe("$0.00");
  });

  it("uses compact notation when compact: true", () => {
    expect(formatUSD(1_500_000, { compact: true })).toBe("$1.5M");
  });

  it("compacts thousands with one fraction digit", () => {
    expect(formatUSD(12_345, { compact: true })).toBe("$12.3K");
  });
});
