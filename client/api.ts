export type UI = Record<string, string>;
export const ui: UI = JSON.parse(
  document.getElementById("ui-catalogue")?.textContent || "{}",
);
export const locale = document.documentElement.dataset.uiLocale || "en";
export const t = (key: string) => ui[key] || key.replaceAll("_", " ");
export interface Session {
  authenticated: boolean;
  csrf_token: string;
  device_id?: string;
  member?: { member_id: string };
}
let sessionPromise: Promise<Session> | undefined;
export function session(refresh = false): Promise<Session> {
  if (refresh) sessionPromise = undefined;
  return (sessionPromise ??= fetch("/api/v1/session", {
    credentials: "same-origin",
    cache: "no-store",
  })
    .then(async (r) => {
      if (!r.ok) throw new Error(t("service_unavailable"));
      return r.json() as Promise<Session>;
    })
    .catch((e) => {
      sessionPromise = undefined;
      throw e;
    }));
}
export class ApiError extends Error {
  constructor(
    public status: number,
    public body: Record<string, unknown>,
  ) {
    super(t(String(body.code || "error")));
  }
}
export interface RequestOptions {
  method?: string;
  body?: unknown;
  version?: number;
  key?: string;
  signal?: AbortSignal;
  keepalive?: boolean;
}
export async function api<T>(
  path: string,
  {
    method = "GET",
    body,
    version,
    key,
    signal,
    keepalive = false,
  }: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET") {
    headers["X-CSRFToken"] = (await session()).csrf_token;
    if (key) headers["Idempotency-Key"] = key;
  }
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (version !== undefined) headers["If-Match"] = `"v${version}"`;
  const r = await fetch("/api/v1" + path, {
    method,
    headers,
    credentials: "same-origin",
    cache: "no-store",
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
    keepalive,
  });
  const data = r.status === 204 ? {} : await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, data);
  return data as T;
}
export function errorText(error: unknown): string {
  if (!navigator.onLine) return t("offline");
  if (error instanceof ApiError)
    return (
      ui[String(error.body.code)] ||
      {
        401: t("sign_in_save"),
        403: t("not_authorized"),
        412: t("version_conflict"),
      }[error.status] ||
      t("error")
    );
  return error instanceof Error && ui[error.message]
    ? ui[error.message]
    : t("error");
}
export interface Preferences {
  version: number;
  theme: string;
  reduced_motion: boolean;
  reader_font_size: number;
  reader_line_height: number;
  reader_margins: string;
  reader_alignment: string;
  reader_theme: string;
  reader_typeface: string;
  reader_layout: string;
}
export function readBootstrap<T>(id: string): T {
  return JSON.parse(document.getElementById(id)?.textContent || "{}") as T;
}
