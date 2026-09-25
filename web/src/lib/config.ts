import "server-only";

export interface WebConfig {
  appOrigin: string;
  apiBaseUrl: string;
  databaseUrl: string;
  issuer: string;
  cognitoDomain: string;
  clientId: string;
  clientSecret?: string;
  scopes: string[];
  encryptionKey: Buffer;
  sessionCookie: string;
  inactivitySeconds: number;
  absoluteSeconds: number;
  loginTransactionSeconds: number;
  apiTimeoutMs: number;
  logoutRedirect?: string;
  secureCookies: boolean;
}

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function positiveInteger(name: string, fallback: number): number {
  const raw = process.env[name]?.trim();
  if (!raw) return fallback;
  const value = Number.parseInt(raw, 10);
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new Error(`${name} must be a positive integer`);
  }
  return value;
}

function url(name: string, value: string, requireHttps: boolean): string {
  const parsed = new URL(value);
  if (requireHttps && parsed.protocol !== "https:") {
    throw new Error(`${name} must use HTTPS`);
  }
  return parsed.toString().replace(/\/$/, "");
}

let cached: WebConfig | undefined;

export function webConfig(): WebConfig {
  if (cached) return cached;
  const production = process.env.NODE_ENV === "production";
  const key = Buffer.from(required("AIRA_WEB_SESSION_ENCRYPTION_KEY"), "base64");
  if (key.length !== 32) {
    throw new Error("AIRA_WEB_SESSION_ENCRYPTION_KEY must decode to 32 bytes");
  }
  const absoluteSeconds = positiveInteger("AIRA_WEB_SESSION_ABSOLUTE_SECONDS", 43_200);
  const inactivitySeconds = positiveInteger(
    "AIRA_WEB_SESSION_INACTIVITY_SECONDS",
    3_600,
  );
  if (inactivitySeconds > absoluteSeconds) {
    throw new Error("Session inactivity timeout cannot exceed absolute timeout");
  }
  cached = {
    appOrigin: url("AIRA_WEB_APP_ORIGIN", required("AIRA_WEB_APP_ORIGIN"), production),
    apiBaseUrl: url("AIRA_WEB_API_BASE_URL", required("AIRA_WEB_API_BASE_URL"), production),
    databaseUrl: required("AIRA_WEB_DATABASE_URL"),
    issuer: url("AIRA_WEB_OIDC_ISSUER", required("AIRA_WEB_OIDC_ISSUER"), true),
    cognitoDomain: url(
      "AIRA_WEB_OIDC_DOMAIN",
      required("AIRA_WEB_OIDC_DOMAIN"),
      true,
    ),
    clientId: required("AIRA_WEB_OIDC_CLIENT_ID"),
    clientSecret: process.env.AIRA_WEB_OIDC_CLIENT_SECRET?.trim() || undefined,
    scopes: (process.env.AIRA_WEB_OIDC_SCOPES || "openid email profile")
      .split(/\s+/)
      .filter(Boolean),
    encryptionKey: key,
    sessionCookie: process.env.AIRA_WEB_SESSION_COOKIE?.trim() || "aira_hosted_session",
    inactivitySeconds,
    absoluteSeconds,
    loginTransactionSeconds: positiveInteger(
      "AIRA_WEB_LOGIN_TRANSACTION_SECONDS",
      600,
    ),
    apiTimeoutMs: positiveInteger("AIRA_WEB_API_TIMEOUT_MS", 10_000),
    logoutRedirect: process.env.AIRA_WEB_OIDC_LOGOUT_REDIRECT?.trim() || undefined,
    secureCookies: production,
  };
  return cached;
}

export function resetConfigForTests(): void {
  cached = undefined;
}
