import { describe, expect, it } from "vitest";
import {
  atomGitPreset,
  baseUrlFromEndpoint,
  catalogRouteDraft,
  connectionKey,
  providerFromCatalogOffer,
} from "./connection";

describe("provider connection helpers", () => {
  it("uses protocol plus normalized base URL as connection identity", () => {
    expect(connectionKey({
      id: "a",
      name: "A",
      protocol: "openai",
      base_url: "HTTPS://EXAMPLE.COM/v1/",
      official_url: "https://example.com",
    })).toBe("openai|https://example.com/v1");
  });

  it("derives base URL from a catalog chat endpoint", () => {
    expect(baseUrlFromEndpoint("https://api.example.com/v1/chat/completions"))
      .toBe("https://api.example.com/v1");
  });

  it("does not invent an endpoint for catalog entries that do not have one", () => {
    const provider = providerFromCatalogOffer({
      provider: "Example AI",
      model: "example-model",
      register: "https://example.com/register",
    });
    expect(provider.base_url).toBe("");
    expect(provider.official_url).toBe("https://example.com/register");
  });

  it("preserves catalog metadata in a route draft", () => {
    const draft = catalogRouteDraft({
      provider: "Example AI",
      model: "m1",
      name: "Model One",
      apiEndpoint: "https://api.example.com/v1/chat/completions",
      capabilities: ["chat", "vision"],
      register: "https://example.com",
      docsUrl: "https://example.com/docs",
      freeSummary: "100 calls/day",
    });
    expect(draft.provider.base_url).toBe("https://api.example.com/v1");
    expect(draft.remote_model).toBe("m1");
    expect(draft.capabilities).toEqual(["chat", "vision"]);
    expect(draft.has_endpoint).toBe(true);
  });

  it("provides the local AtomGit preset", () => {
    expect(atomGitPreset().base_url).toBe("http://127.0.0.1:8080/v1");
  });
});
