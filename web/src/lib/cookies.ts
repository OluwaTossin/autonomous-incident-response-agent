import "server-only";

import type { ResponseCookie } from "next/dist/compiled/@edge-runtime/cookies";
import { webConfig } from "./config";

export const LOGIN_COOKIE_SUFFIX = "_login";

export function sessionCookieOptions(maxAge?: number): Partial<ResponseCookie> {
  const config = webConfig();
  return {
    httpOnly: true,
    secure: config.secureCookies,
    sameSite: "lax",
    path: "/",
    maxAge: maxAge ?? config.absoluteSeconds,
  };
}

export function loginCookieOptions(): Partial<ResponseCookie> {
  const config = webConfig();
  return {
    httpOnly: true,
    secure: config.secureCookies,
    sameSite: "lax",
    path: "/auth",
    maxAge: config.loginTransactionSeconds,
  };
}
