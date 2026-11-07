/** Cliente de la API web (mismo origen vía proxy /api/* de Next.js).
 *
 * - Cookies de sesión (HttpOnly) se envían automáticamente (same-origin).
 * - CSRF: cabecera X-CSRF-Token en toda mutación, token entregado por /me.
 * - 401 -> redirige al login.
 */
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "/api";

let csrfToken: string | null = null;

export function setCsrf(token: string | null) {
  csrfToken = token;
}

export function getCsrf(): string | null {
  return csrfToken;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type Opts = {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
};

async function request<T>(path: string, opts: Opts = {}): Promise<T> {
  const method = opts.method || "GET";
  const headers: Record<string, string> = { ...(opts.headers || {}) };
  let body: BodyInit | undefined;
  if (opts.body instanceof FormData) {
    body = opts.body;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  if (method !== "GET" && csrfToken) {
    headers["X-CSRF-Token"] = csrfToken;
  }
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body,
    credentials: "same-origin",
    cache: "no-store",
  });
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth")) {
    window.location.href = "/login";
    throw new ApiError(401, "Sesión expirada");
  }
  const ct = res.headers.get("content-type") || "";
  const data: unknown = ct.includes("application/json")
    ? await res.json().catch(() => ({}))
    : await res.text();
  if (!res.ok) {
    const detail =
      typeof data === "object" && data !== null && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : `Error ${res.status}`;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: "PUT", body }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  /** Descarga binaria (export ZIP, archivo suelto) respetando la sesión. */
  downloadUrl: (path: string) => `${API_BASE}${path}`,
};

export function loginUrl(): string {
  return `${API_BASE}/auth/login`;
}
