import "server-only";

import {
  createRemoteJWKSet,
  jwtVerify,
  type JWTPayload,
  type JWTVerifyGetKey,
} from "jose";
import type { WebConfig } from "./config";
import { pkceChallenge } from "./security";

export interface ProviderTokens {
  accessToken: string;
  refreshToken?: string;
  idToken?: string;
  accessExpiresAt: Date;
}

export interface VerifiedIdentity {
  issuer: string;
  subject: string;
  email: string;
  displayName: string;
}

export interface OidcProvider {
  authorizationUrl(input: { state: string; nonce: string; verifier: string }): URL;
  exchangeCode(code: string, verifier: string): Promise<ProviderTokens>;
  refresh(refreshToken: string): Promise<ProviderTokens>;
  verifyCallbackTokens(tokens: ProviderTokens, nonce: string): Promise<VerifiedIdentity>;
  verifyAccessToken(accessToken: string): Promise<Date>;
  logoutUrl(): URL | null;
}

export class CognitoOidcProvider implements OidcProvider {
  private readonly jwks: JWTVerifyGetKey;

  constructor(
    private readonly config: WebConfig,
    keyResolver?: JWTVerifyGetKey,
  ) {
    this.jwks =
      keyResolver ||
      createRemoteJWKSet(new URL(`${config.issuer}/.well-known/jwks.json`), {
        timeoutDuration: config.apiTimeoutMs,
        cooldownDuration: 30_000,
      });
  }

  authorizationUrl(input: { state: string; nonce: string; verifier: string }): URL {
    const target = new URL(`${this.config.cognitoDomain}/oauth2/authorize`);
    target.search = new URLSearchParams({
      response_type: "code",
      client_id: this.config.clientId,
      redirect_uri: `${this.config.appOrigin}/auth/callback`,
      scope: this.config.scopes.join(" "),
      state: input.state,
      nonce: input.nonce,
      code_challenge: pkceChallenge(input.verifier),
      code_challenge_method: "S256",
    }).toString();
    return target;
  }

  async exchangeCode(code: string, verifier: string): Promise<ProviderTokens> {
    return this.tokenRequest({
      grant_type: "authorization_code",
      code,
      redirect_uri: `${this.config.appOrigin}/auth/callback`,
      code_verifier: verifier,
    });
  }

  async refresh(refreshToken: string): Promise<ProviderTokens> {
    return this.tokenRequest({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
    });
  }

  async verifyCallbackTokens(
    tokens: ProviderTokens,
    nonce: string,
  ): Promise<VerifiedIdentity> {
    if (!tokens.idToken) throw new Error("Identity token is missing");
    const { payload } = await jwtVerify(tokens.idToken, this.jwks, {
      issuer: this.config.issuer,
      audience: this.config.clientId,
      algorithms: ["RS256"],
    });
    if (payload.token_use !== "id" || payload.nonce !== nonce) {
      throw new Error("Identity token validation failed");
    }
    const subject = requiredClaim(payload, "sub", 255);
    const email = requiredClaim(payload, "email", 320);
    const displayName = optionalClaim(payload, "name", 200) ||
      optionalClaim(payload, "cognito:username", 200) ||
      email;
    await this.verifyAccessToken(tokens.accessToken);
    return { issuer: this.config.issuer, subject, email, displayName };
  }

  async verifyAccessToken(accessToken: string): Promise<Date> {
    const { payload } = await jwtVerify(accessToken, this.jwks, {
      issuer: this.config.issuer,
      algorithms: ["RS256"],
    });
    if (
      payload.token_use !== "access" ||
      payload.client_id !== this.config.clientId ||
      typeof payload.exp !== "number"
    ) {
      throw new Error("Access token validation failed");
    }
    return new Date(payload.exp * 1000);
  }

  logoutUrl(): URL | null {
    if (!this.config.logoutRedirect) return null;
    const target = new URL(`${this.config.cognitoDomain}/logout`);
    target.search = new URLSearchParams({
      client_id: this.config.clientId,
      logout_uri: this.config.logoutRedirect,
    }).toString();
    return target;
  }

  private async tokenRequest(values: Record<string, string>): Promise<ProviderTokens> {
    const headers: Record<string, string> = {
      "content-type": "application/x-www-form-urlencoded",
      accept: "application/json",
    };
    if (this.config.clientSecret) {
      headers.authorization = `Basic ${Buffer.from(
        `${this.config.clientId}:${this.config.clientSecret}`,
      ).toString("base64")}`;
    }
    const body = new URLSearchParams(values);
    if (!this.config.clientSecret) body.set("client_id", this.config.clientId);
    const response = await fetch(`${this.config.cognitoDomain}/oauth2/token`, {
      method: "POST",
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(this.config.apiTimeoutMs),
    });
    if (!response.ok) throw new Error("Identity provider rejected the token request");
    const data = (await response.json()) as Record<string, unknown>;
    if (typeof data.access_token !== "string") {
      throw new Error("Identity provider response is invalid");
    }
    const accessExpiresAt = await this.verifyAccessToken(data.access_token);
    return {
      accessToken: data.access_token,
      refreshToken: typeof data.refresh_token === "string" ? data.refresh_token : undefined,
      idToken: typeof data.id_token === "string" ? data.id_token : undefined,
      accessExpiresAt,
    };
  }
}

function requiredClaim(payload: JWTPayload, name: string, max: number): string {
  const value = optionalClaim(payload, name, max);
  if (!value) throw new Error("Identity token is missing required claims");
  return value;
}

function optionalClaim(payload: JWTPayload, name: string, max: number): string | null {
  const raw = payload[name];
  if (typeof raw !== "string") return null;
  const value = raw.trim();
  return value && value.length <= max ? value : null;
}
