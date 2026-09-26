import { describe, expect, it } from "vitest";
import { resolveApiUrl } from "./client";

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
});
