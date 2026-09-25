import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { webConfig } from "./config";
import { runtime } from "./runtime";

export async function requireBrowserSession() {
  const config = webConfig();
  const sessionId = (await cookies()).get(config.sessionCookie)?.value;
  if (!sessionId) redirect("/auth/login?returnTo=%2Fapp");
  const session = await runtime().sessions.load(sessionId);
  if (!session) redirect("/auth/login?returnTo=%2Fapp");
  return session;
}
