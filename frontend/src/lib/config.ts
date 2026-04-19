/**
 * Browser-visible env (embedded at build time).
 * Prefer NEXT_PUBLIC_API_BASE_URL for deployed ALB / dev stacks.
 */

function stripTrailingSlash(url: string): string {
  return url.replace(/\/$/, "");
}

/** Primary: NEXT_PUBLIC_API_BASE_URL. Legacy: NEXT_PUBLIC_TRIAGE_API_BASE. Fallback: local API. */
export function publicApiBase(): string {
  const primary = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  const legacy = process.env.NEXT_PUBLIC_TRIAGE_API_BASE?.trim();
  const raw = primary || legacy;
  if (raw) return stripTrailingSlash(raw);
  return "http://127.0.0.1:8000";
}

/** @deprecated Use publicApiBase — kept for existing imports */
export function triageApiBase(): string {
  return publicApiBase();
}

/** POST /triage timeout (LLM + RAG can be slow). */
export function publicTriageTimeoutMs(): number {
  const n = Number.parseInt(process.env.NEXT_PUBLIC_TRIAGE_TIMEOUT_MS ?? "", 10);
  if (Number.isFinite(n) && n >= 5000) return n;
  return 120_000;
}

export function publicFeedbackTimeoutMs(): number {
  const n = Number.parseInt(process.env.NEXT_PUBLIC_FEEDBACK_TIMEOUT_MS ?? "", 10);
  if (Number.isFinite(n) && n >= 3000) return n;
  return 45_000;
}

/** Optional: link RB-* tokens in actions to docs (e.g. GitHub blob path to data/runbooks). */
export function runbookDocsBaseUrl(): string | null {
  const raw = process.env.NEXT_PUBLIC_RUNBOOK_DOCS_BASE?.trim();
  return raw ? stripTrailingSlash(raw) : null;
}

/** Matches API ``API_KEY`` when the server enforces ``x-api-key`` (embedded at build time; demo-only). */
export function publicTriageApiKey(): string | null {
  const raw = process.env.NEXT_PUBLIC_TRIAGE_API_KEY?.trim();
  return raw || null;
}

const SESSION_ADMIN_KEY = "aira_session_admin_api_key";

/** Runtime admin header value (never commit); cleared when the tab closes unless re-saved. */
export function getSessionAdminApiKey(): string | null {
  if (typeof window === "undefined") return null;
  const v = sessionStorage.getItem(SESSION_ADMIN_KEY)?.trim();
  return v || null;
}

export function setSessionAdminApiKey(key: string): void {
  sessionStorage.setItem(SESSION_ADMIN_KEY, key.trim());
}

export function clearSessionAdminApiKey(): void {
  sessionStorage.removeItem(SESSION_ADMIN_KEY);
}

/**
 * When true, browser requests omit ``x-admin-api-key``; a same-origin reverse proxy must inject it
 * (see ``docs/security.md``). Static export cannot read process env at runtime — this is build-time.
 */
export function publicAdminProxyInjectsHeaders(): boolean {
  const v = process.env.NEXT_PUBLIC_ADMIN_PROXY_INJECTS_HEADERS?.trim().toLowerCase();
  return v === "1" || v === "true" || v === "yes";
}
