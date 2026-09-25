import { constantTimeEqual, sha256 } from "./security";
import type { BrowserSession } from "./session-service";

export function validateCsrf(
  request: Request,
  session: BrowserSession,
  expectedOrigin: string,
): boolean {
  const origin = request.headers.get("origin");
  const token = request.headers.get("x-csrf-token");
  if (!origin || !token || origin !== expectedOrigin) return false;
  return constantTimeEqual(sha256(token), sha256(session.csrfToken));
}
