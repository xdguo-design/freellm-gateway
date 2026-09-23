import type { CatalogOffer, Provider } from "../../types";

export const CUSTOM_PROVIDER_ID = "__custom__";
export const CATALOG_DRAFT_KEY = "freellm_catalog_model_draft";

export type ProviderDraft = Pick<Provider, "id" | "name" | "protocol" | "base_url" | "official_url">;

export function normalizeBaseUrl(value: string): string {
  const parsed = new URL(value.trim());
  const path = parsed.pathname.replace(/\/+$/, "");
  return `${parsed.protocol.toLowerCase()}//${parsed.host.toLowerCase()}${path}`;
}

export function connectionKey(provider: ProviderDraft): string {
  return `${provider.protocol.toLowerCase()}|${normalizeBaseUrl(provider.base_url)}`;
}

export function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64) || "provider";
}

export function baseUrlFromEndpoint(endpoint: string): string {
  const url = new URL(endpoint);
  const knownSuffixes = ["/chat/completions", "/messages", "/images/generations"];
  let path = url.pathname.replace(/\/+$/, "");
  for (const suffix of knownSuffixes) {
    if (path.endsWith(suffix)) {
      path = path.slice(0, -suffix.length);
      break;
    }
  }
  url.pathname = path || "/";
  url.search = "";
  url.hash = "";
  return url.toString().replace(/\/$/, "");
}

export function providerFromCatalogOffer(offer: CatalogOffer): ProviderDraft {
  const providerName = String(offer.provider || "Catalog Provider").trim();
  const endpoint = typeof offer.apiEndpoint === "string" ? offer.apiEndpoint.trim() : "";
  const official =
    (typeof offer.register === "string" && offer.register) ||
    (typeof offer.docsUrl === "string" && offer.docsUrl) ||
    "";
  const baseUrl = endpoint ? baseUrlFromEndpoint(endpoint) : "";
  let identityHint = providerName;
  if (baseUrl) {
    const parsed = new URL(baseUrl);
    identityHint = `${providerName}-${parsed.host}-${parsed.pathname}`;
  }
  return {
    id: slugify(identityHint),
    name: providerName,
    protocol: "openai",
    base_url: baseUrl,
    official_url: official,
  };
}

export function catalogRouteDraft(offer: CatalogOffer) {
  return {
    provider: providerFromCatalogOffer(offer),
    remote_model: String(offer.model || "").trim(),
    display_name: String(offer.name || offer.model || "").trim(),
    capabilities: Array.isArray(offer.capabilities) && offer.capabilities.length
      ? offer.capabilities.filter((item): item is string => typeof item === "string")
      : ["chat"],
    public_url: typeof offer.register === "string" ? offer.register : "",
    public_docs_url: typeof offer.docsUrl === "string" ? offer.docsUrl : "",
    free_summary: typeof offer.freeSummary === "string" ? offer.freeSummary : "",
    has_endpoint: Boolean(offer.apiEndpoint),
  };
}

export function atomGitPreset(): ProviderDraft {
  return {
    id: "atomgit-codingplan-local",
    name: "AtomGit CodingPlan · 本机 sidecar",
    protocol: "openai",
    base_url: "http://127.0.0.1:8080/v1",
    official_url: "https://ai.atomgit.com",
  };
}
