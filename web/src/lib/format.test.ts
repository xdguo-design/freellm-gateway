import { describe, expect, it } from "vitest";
import { formatCosts, quotaTone } from "./format";

describe("usage formatting", () => {
  it("keeps currencies separate", () => {
    expect(formatCosts([
      { currency: "USD", micros: 1_000_000, amount: 1 },
      { currency: "JPY", micros: 2_000_000, amount: 2 },
    ])).toContain("USD 1");
    expect(formatCosts([
      { currency: "USD", micros: 1_000_000, amount: 1 },
      { currency: "JPY", micros: 2_000_000, amount: 2 },
    ])).toContain("JPY 2");
  });

  it("prioritizes exceeded over warning", () => {
    expect(quotaTone({
      configured: true,
      scope_type: "application",
      scope_id: "app",
      currency: "USD",
      warning_threshold_percent: 80,
      token_limit: 100,
      used_tokens: 100,
      remaining_tokens: 0,
      token_utilization_percent: 100,
      cost_limit_micros: null,
      cost_limit: null,
      used_cost_micros: 0,
      used_cost: 0,
      remaining_cost_micros: null,
      remaining_cost: null,
      cost_utilization_percent: null,
      unpriced_calls: 0,
      other_currency_calls: 0,
      cost_complete: true,
      token_warning: true,
      cost_warning: false,
      token_exceeded: true,
      cost_exceeded: false,
    })).toBe("bad");
  });
});
