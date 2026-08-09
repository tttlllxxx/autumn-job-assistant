import { z } from "zod";

const errorSchema = z.object({ message: z.string(), recovery: z.string().nullable().optional() });

export class ApiError extends Error {
  constructor(message: string, readonly recovery?: string | null, readonly status?: number) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const csrf = localStorage.getItem("csrf_token");
  if (csrf && !["GET", "HEAD"].includes((init.method ?? "GET").toUpperCase())) {
    headers.set("X-CSRF-Token", csrf);
  }
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, credentials: "include", headers });
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    let recovery: string | null | undefined;
    try {
      const parsed = errorSchema.safeParse(await response.json());
      if (parsed.success) ({ message, recovery } = parsed.data);
    } catch {
      // Keep the status-based fallback without exposing response content.
    }
    throw new ApiError(message, recovery, response.status);
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) return (await response.json()) as T;
  return (await response.blob()) as T;
}

export function jsonBody(value: unknown): RequestInit {
  return { method: "POST", body: JSON.stringify(value) };
}

