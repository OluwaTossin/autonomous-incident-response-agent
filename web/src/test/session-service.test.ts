import { describe, expect, it } from "vitest";
import type { HostedApi } from "@/lib/api-client";
import type { WebConfig } from "@/lib/config";
import type { OidcProvider, ProviderTokens } from "@/lib/oidc";
import { SessionService } from "@/lib/session-service";
import type {
  LoginTransactionRecord,
  SessionStore,
  StoredSession,
} from "@/lib/session-store";
import { sha256 } from "@/lib/security";

const NOW = new Date("2026-09-25T12:00:00Z");

class MemoryStore implements SessionStore {
  logins = new Map<string, LoginTransactionRecord & { consumed?: boolean }>();
  sessions = new Map<string, StoredSession>();

  async createLoginTransaction(record: LoginTransactionRecord) {
    this.logins.set(record.idHash, record);
  }
  async consumeLoginTransaction(idHash: string, now: Date) {
    const record = this.logins.get(idHash);
    if (!record || record.consumed || record.expiresAt <= now) return null;
    record.consumed = true;
    return record;
  }
  async createSession(session: StoredSession) {
    this.sessions.set(session.idHash, session);
  }
  async getAndTouchSession(idHash: string, now: Date, inactivitySeconds: number) {
    const session = this.sessions.get(idHash);
    if (
      !session ||
      session.revokedAt ||
      session.inactivityExpiresAt <= now ||
      session.absoluteExpiresAt <= now
    ) return null;
    const touched = {
      ...session,
      lastSeenAt: now,
      inactivityExpiresAt: new Date(
        Math.min(
          session.absoluteExpiresAt.getTime(),
          now.getTime() + inactivitySeconds * 1000,
        ),
      ),
    };
    this.sessions.set(idHash, touched);
    return touched;
  }
  async replaceTokens(
    idHash: string,
    expectedVersion: number,
    encryptedTokens: Buffer,
    accessExpiresAt: Date,
  ) {
    const session = this.sessions.get(idHash);
    if (!session || session.version !== expectedVersion) return false;
    this.sessions.set(idHash, {
      ...session,
      encryptedTokens,
      accessExpiresAt,
      version: session.version + 1,
    });
    return true;
  }
  async revokeSession(idHash: string, now: Date) {
    const session = this.sessions.get(idHash);
    if (session) this.sessions.set(idHash, { ...session, revokedAt: now });
  }
}

class Provider implements OidcProvider {
  refreshes = 0;
  authorizationUrl(input: { state: string; nonce: string; verifier: string }) {
    const url = new URL("https://identity.example/authorize");
    url.search = new URLSearchParams(input).toString();
    return url;
  }
  async exchangeCode(): Promise<ProviderTokens> {
    return this.tokens("access-one", NOW.getTime() + 60_000);
  }
  async refresh(): Promise<ProviderTokens> {
    this.refreshes += 1;
    return this.tokens("access-refreshed", NOW.getTime() + 3_600_000);
  }
  async verifyCallbackTokens() {
    return {
      issuer: "https://issuer.example",
      subject: "subject-1",
      email: "operator@example.com",
      displayName: "AIRA Operator",
    };
  }
  async verifyAccessToken() { return new Date(NOW.getTime() + 60_000); }
  logoutUrl() { return null; }
  private tokens(accessToken: string, expires: number): ProviderTokens {
    return {
      accessToken,
      refreshToken: "refresh-secret",
      idToken: "id-secret",
      accessExpiresAt: new Date(expires),
    };
  }
}

const api = {
  bootstrap: async () => ({ user_id: "00000000-0000-4000-8000-000000000001", organizations: [] }),
} as unknown as HostedApi;

const config: WebConfig = {
  appOrigin: "http://localhost:3001",
  apiBaseUrl: "http://localhost:8000",
  databaseUrl: "postgresql://unused",
  issuer: "https://issuer.example",
  cognitoDomain: "https://identity.example",
  clientId: "client",
  scopes: ["openid"],
  encryptionKey: Buffer.alloc(32, 4),
  sessionCookie: "aira_session",
  inactivitySeconds: 300,
  absoluteSeconds: 3_600,
  loginTransactionSeconds: 60,
  apiTimeoutMs: 1_000,
  secureCookies: false,
};

describe("server-mediated sessions", () => {
  it("creates state, nonce and PKCE then rotates to a distinct opaque session", async () => {
    const store = new MemoryStore();
    const provider = new Provider();
    const service = new SessionService(config, store, provider, api, () => NOW);
    const begun = await service.beginLogin("/app?incident=1");
    const state = begun.authorizationUrl.searchParams.get("state")!;

    const completed = await service.completeLogin(
      begun.transactionId,
      "authorization-code",
      state,
    );

    expect(completed.sessionId).not.toBe(begun.transactionId);
    expect(completed.returnPath).toBe("/app?incident=1");
    expect(store.sessions.get(sha256(completed.sessionId))?.encryptedTokens.toString())
      .not.toContain("access-one");
    await expect(
      service.completeLogin(begun.transactionId, "authorization-code", state),
    ).rejects.toThrow("invalid");
  });

  it("rejects mismatched state and consumes the login transaction", async () => {
    const store = new MemoryStore();
    const service = new SessionService(config, store, new Provider(), api, () => NOW);
    const begun = await service.beginLogin("https://hostile.example");
    await expect(
      service.completeLogin(begun.transactionId, "code", "wrong-state"),
    ).rejects.toThrow("invalid");
    expect(store.logins.get(sha256(begun.transactionId))?.consumed).toBe(true);
  });

  it("refreshes expired access credentials server-side and revokes on logout", async () => {
    const store = new MemoryStore();
    const provider = new Provider();
    const service = new SessionService(config, store, provider, api, () => NOW);
    const begun = await service.beginLogin();
    const completed = await service.completeLogin(
      begun.transactionId,
      "code",
      begun.authorizationUrl.searchParams.get("state")!,
    );
    const stored = store.sessions.get(sha256(completed.sessionId))!;
    store.sessions.set(stored.idHash, {
      ...stored,
      accessExpiresAt: new Date(NOW.getTime() + 10_000),
    });

    const loaded = await service.load(completed.sessionId);
    expect(loaded?.accessToken).toBe("access-refreshed");
    expect(provider.refreshes).toBe(1);
    await service.revoke(completed.sessionId);
    expect(await service.load(completed.sessionId)).toBeNull();
  });
});
