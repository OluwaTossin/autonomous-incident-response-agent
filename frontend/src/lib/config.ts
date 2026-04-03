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
