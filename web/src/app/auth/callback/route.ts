import { NextRequest, NextResponse } from "next/server";
import { webConfig } from "@/lib/config";
import {
  LOGIN_COOKIE_SUFFIX,
  loginCookieOptions,
  sessionCookieOptions,
} from "@/lib/cookies";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const config = webConfig();
  const loginCookie = `${config.sessionCookie}${LOGIN_COOKIE_SUFFIX}`;
  const transactionId = request.cookies.get(loginCookie)?.value;
  const code = request.nextUrl.searchParams.get("code");
  const state = request.nextUrl.searchParams.get("state");
  if (!transactionId || !code || !state || request.nextUrl.searchParams.has("error")) {
    return failed(config.appOrigin, loginCookie);
  }
  try {
    const completed = await runtime().sessions.completeLogin(
      transactionId,
      code,
      state,
    );
    const response = NextResponse.redirect(
      new URL(completed.returnPath, config.appOrigin),
    );
    response.headers.set("cache-control", "private, no-store");
    response.cookies.set(config.sessionCookie, completed.sessionId, {
      ...sessionCookieOptions(),
      expires: completed.absoluteExpiresAt,
    });
    response.cookies.set(loginCookie, "", {
      ...loginCookieOptions(),
      maxAge: 0,
      expires: new Date(0),
    });
    return response;
  } catch {
    return failed(config.appOrigin, loginCookie);
  }
}

function failed(origin: string, loginCookie: string): NextResponse {
  const response = NextResponse.redirect(
    new URL("/login?error=authentication_failed", origin),
  );
  response.headers.set("cache-control", "private, no-store");
  response.cookies.set(loginCookie, "", {
    ...loginCookieOptions(),
    maxAge: 0,
    expires: new Date(0),
  });
  return response;
}
