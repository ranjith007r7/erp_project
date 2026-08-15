/**
 * Every call to the backend goes through here. Two jobs:
 * 1. Know the backend's URL (from an environment variable, never hardcoded).
 * 2. Attach the JWT token automatically, so no page has to remember to do it.
 *
 * The token is stored in localStorage for now (simplest thing that works).
 * A production-hardened version would use an httpOnly cookie instead, but
 * localStorage is fine while we're building and demoing.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("erp_token");
}

export function setToken(token: string) {
  localStorage.setItem("erp_token", token);
}

export function clearToken() {
  localStorage.removeItem("erp_token");
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  auth?: boolean;
};

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, auth = false } = options;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({ detail: "Unknown error" }));
    const message =
      typeof errorBody.detail === "string"
        ? errorBody.detail
        : JSON.stringify(errorBody.detail);
    throw new Error(message);
  }

  // A 204 (or any response with genuinely no body, e.g. our DELETE routes)
  // has nothing for res.json() to parse — calling it anyway throws a
  // browser SyntaxError even though the request succeeded. Caught this by
  // tracing the real HTTP response (curl -i) against every call site
  // rather than assuming success always means a JSON body.
  if (res.status === 204) {
    return undefined as T;
  }
  const text = await res.text();
  return text ? JSON.parse(text) : (undefined as T);
}

/**
 * For endpoints that return a file (CSV export) rather than JSON. Reuses
 * the same token-attachment logic as apiRequest, then triggers a normal
 * browser "Save As" download instead of parsing a response body.
 */
export async function apiDownload(path: string, filename: string): Promise<void> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_URL}${path}`, { headers });
  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(typeof errorBody.detail === "string" ? errorBody.detail : "Export failed");
  }

  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}
