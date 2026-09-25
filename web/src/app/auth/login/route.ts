import { NextRequest, NextResponse } from "next/server";
import { webConfig } from "@/lib/config";
import { LOGIN_COOKIE_SUFFIX, loginCookieOptions } from "@/lib/cookies";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest): Promise<NextResponse> {
  const config = webConfig();
  const login = await runtime().sessions.beginLogin(
    request.nextUrl.searchParams.get("returnTo"),
  );
  const response = NextResponse.redirect(login.authorizationUrl);
  response.headers.set("cache-control", "private, no-store");
  response.cookies.set(
    `${config.sessionCookie}${LOGIN_COOKIE_SUFFIX}`,
    login.transactionId,
    loginCookieOptions(),
  );
  return response;
}
