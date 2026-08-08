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

  return res.json();
}
