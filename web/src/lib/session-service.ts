import "server-only";

import type { HostedApi } from "./api-client";
import type { WebConfig } from "./config";
import type { OidcProvider, ProviderTokens } from "./oidc";
import {
  constantTimeEqual,
  decryptJson,
  encryptJson,
  randomToken,
  safeReturnPath,
  sha256,
} from "./security";
import type { SessionStore, StoredSession } from "./session-store";
import { structuredLog } from "./observability";

interface LoginSecrets {
  nonce: string;
  verifier: string;
}

interface SessionSecrets {
  tokens: ProviderTokens;
  csrfToken: string;
}

export interface BrowserSession {
  idHash: string;
  userId: string;
  displayName: string;
  email: string;
  csrfToken: string;
  accessToken: string;
  absoluteExpiresAt: Date;
}

export interface BegunLogin {
  transactionId: string;
  authorizationUrl: URL;
  expiresAt: Date;
}

export interface CompletedLogin {
  sessionId: string;
  returnPath: string;
  absoluteExpiresAt: Date;
}

export class SessionService {
  constructor(
    private readonly config: WebConfig,
    private readonly store: SessionStore,
    private readonly provider: OidcProvider,
    private readonly api: HostedApi,
    private readonly clock: () => Date = () => new Date(),
  ) {}

  async beginLogin(returnPath?: string | null): Promise<BegunLogin> {
    const now = this.clock();
    const transactionId = randomToken();
    const state = randomToken();
    const nonce = randomToken();
    const verifier = randomToken(48);
    const expiresAt = new Date(
      now.getTime() + this.config.loginTransactionSeconds * 1000,
    );
    await this.store.createLoginTransaction({
      idHash: sha256(transactionId),
      stateHash: sha256(state),
      encryptedPayload: encryptJson({ nonce, verifier }, this.config.encryptionKey),
      returnPath: safeReturnPath(returnPath),
      createdAt: now,
      expiresAt,
    });
    return {
      transactionId,
      authorizationUrl: this.provider.authorizationUrl({ state, nonce, verifier }),
      expiresAt,
    };
  }

  async completeLogin(
    transactionId: string,
    code: string,
    state: string,
  ): Promise<CompletedLogin> {
    const now = this.clock();
    const transaction = await this.store.consumeLoginTransaction(
      sha256(transactionId),
      now,
    );
    if (!transaction || !constantTimeEqual(transaction.stateHash, sha256(state))) {
      structuredLog("warn", "auth.callback_failed", "Login transaction validation failed", {
        error_category: "authorization",
      });
      throw new Error("Login transaction is invalid");
    }
    const secrets = decryptJson<LoginSecrets>(
      transaction.encryptedPayload,
      this.config.encryptionKey,
    );
    const tokens = await this.provider.exchangeCode(code, secrets.verifier);
    const identity = await this.provider.verifyCallbackTokens(tokens, secrets.nonce);
    const bootstrap = await this.api.bootstrap(tokens.accessToken, tokens.idToken);
    const sessionId = randomToken();
    const csrfToken = randomToken();
    const absoluteExpiresAt = new Date(
      now.getTime() + this.config.absoluteSeconds * 1000,
    );
    const inactivityExpiresAt = new Date(
      Math.min(
        absoluteExpiresAt.getTime(),
        now.getTime() + this.config.inactivitySeconds * 1000,
      ),
    );
    await this.store.createSession({
      idHash: sha256(sessionId),
      userId: bootstrap.user_id,
      providerIssuer: identity.issuer,
      providerSubject: identity.subject,
      displayName: identity.displayName,
      email: identity.email,
      encryptedTokens: encryptJson({ tokens, csrfToken }, this.config.encryptionKey),
      csrfHash: sha256(csrfToken),
      accessExpiresAt: tokens.accessExpiresAt,
      createdAt: now,
      lastSeenAt: now,
      inactivityExpiresAt,
      absoluteExpiresAt,
      revokedAt: null,
      version: 1,
    });
    structuredLog("info", "auth.session_created", "Browser session created", {
      result: "succeeded",
    });
    return { sessionId, returnPath: transaction.returnPath, absoluteExpiresAt };
  }

  async load(sessionId: string): Promise<BrowserSession | null> {
    const now = this.clock();
    let stored = await this.store.getAndTouchSession(
      sha256(sessionId),
      now,
      this.config.inactivitySeconds,
    );
    if (!stored) return null;
    let secrets = this.secrets(stored);
    if (!constantTimeEqual(stored.csrfHash, sha256(secrets.csrfToken))) {
      await this.store.revokeSession(stored.idHash, now);
      return null;
    }
    if (stored.accessExpiresAt.getTime() <= now.getTime() + 30_000) {
      stored = await this.refresh(stored, secrets);
      if (!stored) return null;
      secrets = this.secrets(stored);
    }
    return {
      idHash: stored.idHash,
      userId: stored.userId,
      displayName: stored.displayName,
      email: stored.email,
      csrfToken: secrets.csrfToken,
      accessToken: secrets.tokens.accessToken,
      absoluteExpiresAt: stored.absoluteExpiresAt,
    };
  }

  async revoke(sessionId: string): Promise<void> {
    await this.store.revokeSession(sha256(sessionId), this.clock());
  }

  private async refresh(
    stored: StoredSession,
    secrets: SessionSecrets,
  ): Promise<StoredSession | null> {
    if (!secrets.tokens.refreshToken) {
      structuredLog("warn", "auth.refresh_failed", "Session has no refresh credential", {
        error_category: "authorization",
      });
      await this.store.revokeSession(stored.idHash, this.clock());
      return null;
    }
    try {
      const refreshed = await this.provider.refresh(secrets.tokens.refreshToken);
      const nextTokens: ProviderTokens = {
        ...refreshed,
        refreshToken: refreshed.refreshToken || secrets.tokens.refreshToken,
      };
      const encryptedTokens = encryptJson(
        { tokens: nextTokens, csrfToken: secrets.csrfToken },
        this.config.encryptionKey,
      );
      const replaced = await this.store.replaceTokens(
        stored.idHash,
        stored.version,
        encryptedTokens,
        nextTokens.accessExpiresAt,
      );
      if (replaced) {
        return {
          ...stored,
          encryptedTokens,
          accessExpiresAt: nextTokens.accessExpiresAt,
          version: stored.version + 1,
        };
      }
      return this.store.getAndTouchSession(
        stored.idHash,
        this.clock(),
        this.config.inactivitySeconds,
      );
    } catch {
      structuredLog("warn", "auth.refresh_failed", "Identity provider refresh failed", {
        error_category: "provider",
      });
      await this.store.revokeSession(stored.idHash, this.clock());
      return null;
    }
  }

  private secrets(stored: StoredSession): SessionSecrets {
    return decryptJson<SessionSecrets>(
      stored.encryptedTokens,
      this.config.encryptionKey,
    );
  }
}
