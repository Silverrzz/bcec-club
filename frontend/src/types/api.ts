export type QueryPrimitive = string | number | boolean | null | undefined;
export type QueryValue = QueryPrimitive | readonly QueryPrimitive[];
export type QueryParams = Record<string, QueryValue> | URLSearchParams;

export interface ApiFieldError {
  field?: string;
  message: string;
  code?: string;
}

export interface ApiErrorPayload {
  detail?: unknown;
  message?: string;
  error?: string;
  errors?: ApiFieldError[] | Record<string, string | string[]>;
  [key: string]: unknown;
}

export interface SessionPayload {
  authenticated: boolean;
  admin_configured?: boolean;
  secure_context?: boolean;
  csrf_token?: string | null;
  csrfToken?: string | null;
  user?: {
    name?: string;
    role?: string;
    [key: string]: unknown;
  } | null;
  [key: string]: unknown;
}

export interface ListResponse<T> {
  items: T[];
  total?: number;
  next_cursor?: string | null;
}
