const ADMIN_TOKEN_KEY = "freellm_gateway_admin_token";
const LEGACY_ADMIN_TOKEN_KEY = "freellm_admin_token";

declare global {
  interface Window {
    __FREELLM_GATEWAY_PORT__?: number;
  }
}

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function browserSessionStorage(): Storage | null {
  return typeof window !== "undefined" && typeof window.sessionStorage !== "undefined"
    ? window.sessionStorage
    : null;
}

export function getAdminToken(): string {
  const storage = browserSessionStorage();
  if (!storage) return "";
  const current = storage.getItem(ADMIN_TOKEN_KEY);
  if (current) return current;
  const legacy = storage.getItem(LEGACY_ADMIN_TOKEN_KEY) ?? "";
  if (legacy) storage.setItem(ADMIN_TOKEN_KEY, legacy);
  return legacy;
}

export function setAdminToken(value: string): void {
  const storage = browserSessionStorage();
  if (!storage) return;
  if (value) storage.setItem(ADMIN_TOKEN_KEY, value);
  else storage.removeItem(ADMIN_TOKEN_KEY);
}

export function resolveApiUrl(path: string, desktopPort?: number): string {
  if (/^https?:\/\//i.test(path)) return path;
  const port = desktopPort ?? (
    typeof window !== "undefined" ? window.__FREELLM_GATEWAY_PORT__ : undefined
  );
  if (!port) return path;
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `http://127.0.0.1:${port}${suffix}`;
}

export function buildApiHeaders(token: string, hasBody = false): Headers {
  const headers = new Headers({ Accept: "application/json" });
  if (token) headers.set("X-Free-LLM-Token", token);
  if (hasBody) headers.set("Content-Type", "application/json");
  return headers;
}

export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown; signal?: AbortSignal } = {},
): Promise<T> {
  const headers = buildApiHeaders(getAdminToken(), options.body !== undefined);
  let body: string | undefined;
  if (options.body !== undefined) {
    body = JSON.stringify(options.body);
  }
  const response = await fetch(resolveApiUrl(path), {
    method: options.method ?? "GET",
    headers,
    body,
    signal: options.signal,
  });
  if (!response.ok) {
    let detail: unknown = response.statusText;
    try {
      const parsed = (await response.json()) as { detail?: unknown };
      detail = parsed.detail ?? parsed;
    } catch {
      detail = await response.text();
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
