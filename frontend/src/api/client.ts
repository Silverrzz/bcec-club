import type { ApiErrorPayload, ApiFieldError, QueryParams } from "@/types/api";

export interface RequestOptions {
  body?: unknown;
  headers?: HeadersInit | undefined;
  query?: QueryParams | undefined;
  signal?: AbortSignal | undefined;
}

let csrfToken = "";

export class ApiError extends Error {
  readonly status: number;
  readonly payload: ApiErrorPayload | null;

  constructor(status: number, message: string, payload: ApiErrorPayload | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }

  get fieldErrors(): Record<string, string[]> {
    const errors = this.payload?.errors ?? detailFieldErrors(this.payload?.detail);
    if (!errors) return {};

    if (Array.isArray(errors)) {
      return errors.reduce<Record<string, string[]>>((result, error) => {
        const field = error.field ?? "form";
        (result[field] ??= []).push(error.message);
        return result;
      }, {});
    }

    return Object.entries(errors).reduce<Record<string, string[]>>((result, [field, value]) => {
      result[field] = Array.isArray(value) ? value : [value];
      return result;
    }, {});
  }
}

function detailFieldErrors(detail: unknown): ApiFieldError[] | undefined {
  if (!Array.isArray(detail)) return undefined;
  const errors = detail.flatMap<ApiFieldError>((item) => {
    if (typeof item === "string") return [{ field: "form", message: item }];
    if (!item || typeof item !== "object") return [];
    const value = item as { loc?: unknown; msg?: unknown; message?: unknown };
    const location = Array.isArray(value.loc)
      ? value.loc.filter((part) => part !== "body").map(String).join(".")
      : "form";
    const message = typeof value.msg === "string"
      ? value.msg
      : typeof value.message === "string"
        ? value.message
        : "Invalid value.";
    return [{ field: location || "form", message }];
  });
  return errors.length ? errors : undefined;
}

export function setCsrfToken(token: string | null | undefined): void {
  csrfToken = token ?? "";
}

function appendQuery(path: string, query?: QueryParams): string {
  if (!query) return path;
  const params = query instanceof URLSearchParams ? new URLSearchParams(query) : new URLSearchParams();

  if (!(query instanceof URLSearchParams)) {
    for (const [key, rawValue] of Object.entries(query)) {
      const values = Array.isArray(rawValue) ? rawValue : [rawValue];
      for (const value of values) {
        if (value !== null && value !== undefined && value !== "") {
          params.append(key, String(value));
        }
      }
    }
  }

  const suffix = params.toString();
  if (!suffix) return path;
  return `${path}${path.includes("?") ? "&" : "?"}${suffix}`;
}

function errorMessage(status: number, payload: ApiErrorPayload | null): string {
  if (typeof payload?.detail === "string") return payload.detail;
  if (Array.isArray(payload?.detail)) {
    const messages = detailFieldErrors(payload.detail)?.map((error) => error.message) ?? [];
    if (messages.length) return [...new Set(messages)].join(" ");
  }
  if (payload?.message) return payload.message;
  if (payload?.error) return payload.error;
  if (status === 401) return "Your session has expired. Please sign in again.";
  if (status === 403) return "You do not have permission to do that.";
  if (status === 404) return "The requested resource could not be found.";
  if (status >= 500) return "The server could not complete the request.";
  return "The request could not be completed.";
}

async function parseResponse(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) return response.json();
  const text = await response.text();
  return text || undefined;
}

async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");

  let body: BodyInit | undefined;
  if (options.body instanceof FormData || options.body instanceof URLSearchParams || typeof options.body === "string") {
    body = options.body;
  } else if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.body);
  }

  if (!/^(GET|HEAD|OPTIONS)$/i.test(method) && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }

  const init: RequestInit = {
    method,
    headers,
    credentials: "same-origin",
  };
  if (body !== undefined) init.body = body;
  if (options.signal) init.signal = options.signal;

  let response: Response;
  try {
    response = await fetch(appendQuery(path, options.query), init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "Could not reach the server. Check your connection and try again.");
  }

  const payload = await parseResponse(response);
  if (!response.ok) {
    const errorPayload = typeof payload === "object" && payload !== null ? (payload as ApiErrorPayload) : null;
    if (response.status === 401 && path.startsWith("/api/admin")) {
      window.dispatchEvent(new CustomEvent("cope:session-expired"));
    }
    throw new ApiError(response.status, errorMessage(response.status, errorPayload), errorPayload);
  }

  return payload as T;
}

export const api = {
  get: <T>(path: string, options?: Omit<RequestOptions, "body">) => request<T>("GET", path, options),
  post: <T>(path: string, options?: RequestOptions) => request<T>("POST", path, options),
  put: <T>(path: string, options?: RequestOptions) => request<T>("PUT", path, options),
  patch: <T>(path: string, options?: RequestOptions) => request<T>("PATCH", path, options),
  delete: <T>(path: string, options?: RequestOptions) => request<T>("DELETE", path, options),
};

export default api;
