import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetConfigForTests } from "@/lib/config";
import { loginCookieOptions, sessionCookieOptions } from "@/lib/cookies";

beforeEach(() => {
  vi.stubEnv("NODE_ENV", "production");
  process.env.AIRA_WEB_APP_ORIGIN = "https://aira.example";
  process.env.AIRA_WEB_API_BASE_URL = "https://api.aira.example";
  process.env.AIRA_WEB_DATABASE_URL = "postgresql://example";
  process.env.AIRA_WEB_OIDC_ISSUER = "https://issuer.example";
  process.env.AIRA_WEB_OIDC_DOMAIN = "https://login.example";
  process.env.AIRA_WEB_OIDC_CLIENT_ID = "client";
  process.env.AIRA_WEB_SESSION_ENCRYPTION_KEY = Buffer.alloc(32, 1).toString("base64");
  resetConfigForTests();
});

describe("hosted cookie policy", () => {
  it("uses bounded Secure HttpOnly SameSite cookies", () => {
    expect(sessionCookieOptions()).toMatchObject({
      httpOnly: true,
      secure: true,
      sameSite: "lax",
      path: "/",
      maxAge: 43_200,
    });
    expect(loginCookieOptions()).toMatchObject({
      httpOnly: true,
      secure: true,
      sameSite: "lax",
      path: "/auth",
      maxAge: 600,
    });
  });
});
