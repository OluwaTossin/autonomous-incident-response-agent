import { NextRequest, NextResponse } from "next/server";
import { webConfig } from "@/lib/config";
import { sessionCookieOptions } from "@/lib/cookies";
import { validateCsrf } from "@/lib/csrf";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const config = webConfig();
  const sessionId = request.cookies.get(config.sessionCookie)?.value;
  if (sessionId) {
    const session = await runtime().sessions.load(sessionId);
    if (session && !validateCsrf(request, session, config.appOrigin)) {
      return NextResponse.json(
        { error: { code: "forbidden", message: "Request verification failed" } },
        { status: 403, headers: { "cache-control": "private, no-store" } },
      );
    }
    await runtime().sessions.revoke(sessionId);
  }
  const providerLogout = runtime().provider.logoutUrl();
  const response = NextResponse.redirect(
    providerLogout || new URL("/login?loggedOut=1", config.appOrigin),
    303,
  );
  response.headers.set("cache-control", "private, no-store");
  response.cookies.set(config.sessionCookie, "", {
    ...sessionCookieOptions(0),
    expires: new Date(0),
  });
  return response;
}
