import { NextRequest } from "next/server";
import { withBffSession } from "@/lib/bff";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";
type Context = { params: Promise<{ organizationId: string; workspaceId: string }> };

export async function GET(request: NextRequest, context: Context) {
  const { organizationId, workspaceId } = await context.params;
  return withBffSession(request, false, (session) =>
    runtime().api.getUsage(session.accessToken, organizationId, workspaceId),
  );
}
