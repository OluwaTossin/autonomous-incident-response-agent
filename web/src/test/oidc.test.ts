import {
  SignJWT,
  createLocalJWKSet,
  exportJWK,
  generateKeyPair,
} from "jose";
import { describe, expect, it } from "vitest";
import type { WebConfig } from "@/lib/config";
import { CognitoOidcProvider } from "@/lib/oidc";

const config: WebConfig = {
  appOrigin: "https://aira.example",
  apiBaseUrl: "https://api.aira.example",
  databaseUrl: "postgresql://unused",
  issuer: "https://issuer.example",
  cognitoDomain: "https://login.example",
  clientId: "client-123",
  scopes: ["openid", "email", "profile"],
  encryptionKey: Buffer.alloc(32),
  sessionCookie: "aira_session",
  inactivitySeconds: 300,
  absoluteSeconds: 3_600,
  loginTransactionSeconds: 60,
  apiTimeoutMs: 1_000,
  secureCookies: true,
};

describe("Cognito OIDC boundary", () => {
  it("generates authorization-code PKCE parameters", () => {
    const provider = new CognitoOidcProvider(config);
    const url = provider.authorizationUrl({
      state: "random-state",
      nonce: "random-nonce",
      verifier: "long-code-verifier-value",
    });
    expect(url.pathname).toBe("/oauth2/authorize");
    expect(url.searchParams.get("response_type")).toBe("code");
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
    expect(url.searchParams.get("code_challenge")).not.toBe("long-code-verifier-value");
    expect(url.searchParams.get("state")).toBe("random-state");
    expect(url.searchParams.get("nonce")).toBe("random-nonce");
  });

  it("verifies signed ID/access tokens and callback nonce", async () => {
    const { privateKey, publicKey } = await generateKeyPair("RS256");
    const publicJwk = await exportJWK(publicKey);
    const resolver = createLocalJWKSet({ keys: [{ ...publicJwk, kid: "key-1", alg: "RS256" }] });
    const provider = new CognitoOidcProvider(config, resolver);
    const now = Math.floor(Date.now() / 1000);
    const idToken = await new SignJWT({
      token_use: "id",
      nonce: "nonce-1",
      email: "operator@example.com",
      name: "Operator",
    })
      .setProtectedHeader({ alg: "RS256", kid: "key-1" })
      .setIssuer(config.issuer)
      .setAudience(config.clientId)
      .setSubject("subject-1")
      .setIssuedAt(now)
      .setExpirationTime(now + 300)
      .sign(privateKey);
    const accessToken = await new SignJWT({
      token_use: "access",
      client_id: config.clientId,
    })
      .setProtectedHeader({ alg: "RS256", kid: "key-1" })
      .setIssuer(config.issuer)
      .setSubject("subject-1")
      .setIssuedAt(now)
      .setExpirationTime(now + 300)
      .sign(privateKey);
    const tokens = {
      accessToken,
      idToken,
      refreshToken: "server-only-refresh",
      accessExpiresAt: new Date((now + 300) * 1000),
    };

    await expect(provider.verifyCallbackTokens(tokens, "nonce-1")).resolves.toEqual({
      issuer: config.issuer,
      subject: "subject-1",
      email: "operator@example.com",
      displayName: "Operator",
    });
    await expect(provider.verifyCallbackTokens(tokens, "wrong-nonce")).rejects.toThrow(
      "validation failed",
    );
    const mismatchedAccessToken = await new SignJWT({
      token_use: "access",
      client_id: config.clientId,
    })
      .setProtectedHeader({ alg: "RS256", kid: "key-1" })
      .setIssuer(config.issuer)
      .setSubject("different-subject")
      .setIssuedAt(now)
      .setExpirationTime(now + 300)
      .sign(privateKey);
    await expect(
      provider.verifyCallbackTokens(
        { ...tokens, accessToken: mismatchedAccessToken },
        "nonce-1",
      ),
    ).rejects.toThrow("subjects do not match");
  });
});
