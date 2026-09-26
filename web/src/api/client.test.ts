import { describe, expect, it } from "vitest";
import { buildApiHeaders, resolveApiUrl } from "./client";

describe("desktop API routing", () => {
  it("keeps relative paths in the normal web admin", () => {
    expect(resolveApiUrl("/api/admin/overview")).toBe("/api/admin/overview");
  });

  it("routes relative API calls to the injected desktop gateway", () => {
    expect(resolveApiUrl("/api/admin/overview", 18900))
      .toBe("http://127.0.0.1:18900/api/admin/overview");
    expect(resolveApiUrl("health", 18900))
      .toBe("http://127.0.0.1:18900/health");
  });

  it("never rewrites absolute HTTP URLs", () => {
    expect(resolveApiUrl("https://example.com/api", 18900))
      .toBe("https://example.com/api");
  });

  it("uses the WorkBuddy-compatible token header for admin requests", () => {
    const headers = buildApiHeaders("admin-token", true);
    expect(headers.get("X-Free-LLM-Token")).toBe("admin-token");
    expect(headers.get("Authorization")).toBeNull();
    expect(headers.get("Content-Type")).toBe("application/json");
  });
});
