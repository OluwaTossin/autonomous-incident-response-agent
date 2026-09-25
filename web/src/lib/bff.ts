import "server-only";

import { NextRequest, NextResponse } from "next/server";
import { HostedApiError } from "./api-client";
import { webConfig } from "./config";
import { sessionCookieOptions } from "./cookies";
import { validateCsrf } from "./csrf";
import { runtime } from "./runtime";
import type { BrowserSession } from "./session-service";
import type { BrowserError, BrowserErrorCode } from "./types";

export async function withBffSession(
  request: NextRequest,
  mutation: boolean,
  operation: (session: BrowserSession) => Promise<unknown>,
): Promise<NextResponse> {
  const config = webConfig();
  const rawSessionId = request.cookies.get(config.sessionCookie)?.value;
  if (!rawSessionId) return errorResponse(401, "unauthenticated", "Sign in is required");
  const session = await runtime().sessions.load(rawSessionId);
  if (!session) {
    return clearSession(
      errorResponse(401, "unauthenticated", "Your session has expired"),
    );
  }
  if (mutation && !validateCsrf(request, session, config.appOrigin)) {
    return errorResponse(403, "forbidden", "Request verification failed");
  }
  try {
    const payload = await operation(session);
    return NextResponse.json(payload, {
      headers: { "cache-control": "private, no-store" },
    });
  } catch (error) {
    if (error instanceof HostedApiError) {
      const response = errorResponse(error.status, error.kind, error.message);
      if (error.status === 401) {
        await runtime().sessions.revoke(rawSessionId);
        return clearSession(response);
      }
      return response;
    }
    return errorResponse(500, "unexpected", "The request could not be completed");
  }
}

export function errorResponse(
  status: number,
  code: BrowserErrorCode,
  message: string,
): NextResponse<BrowserError> {
  return NextResponse.json(
    { error: { code, message } },
    { status, headers: { "cache-control": "private, no-store" } },
  );
}

function clearSession(response: NextResponse): NextResponse {
  const config = webConfig();
  response.cookies.set(config.sessionCookie, "", {
    ...sessionCookieOptions(0),
    expires: new Date(0),
  });
  return response;
}
