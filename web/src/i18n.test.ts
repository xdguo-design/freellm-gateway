import { describe, expect, it } from "vitest";
import { statusLabel, translate, translateErrorDetail } from "./i18n";

describe("i18n", () => {
  it("translates navigation and interpolates values", () => {
    expect(translate("zh", "nav.models")).toBe("模型池");
    expect(translate("en", "nav.models")).toBe("Model Pool");
    expect(translate("en", "models.bulkDone", { created: 3, skipped: 1 }))
      .toBe("Bulk import complete: 3 created, 1 skipped.");
  });

  it("localizes status values without changing unknown raw values", () => {
    expect(statusLabel("zh", "rate_limited")).toBe("限流");
    expect(statusLabel("en", "published")).toBe("Published");
    expect(statusLabel("en", "vendor_custom")).toBe("vendor_custom");
  });

  it("localizes known backend errors and preserves unknown diagnostics", () => {
    expect(translateErrorDetail("zh", { detail: "provider not found" })).toBe("Provider 不存在。");
    expect(translateErrorDetail("en", { detail: "route not found" })).toBe("Model route not found.");
    expect(translateErrorDetail("en", new Error("socket exploded"))).toBe("socket exploded");
  });

  it("formats quota exceeded details", () => {
    expect(translateErrorDetail("zh", {
      detail: { code: "quota_exceeded", scope_id: "app-a", resource: "tokens" },
    })).toBe("app-a 的 tokens 配额已超限。");
  });
});
