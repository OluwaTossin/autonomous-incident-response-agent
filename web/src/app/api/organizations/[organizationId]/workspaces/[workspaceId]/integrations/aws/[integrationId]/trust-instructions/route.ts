import { NextRequest } from "next/server";
import { withBffSession } from "@/lib/bff";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest, context: { params: Promise<{ organizationId: string; workspaceId: string; integrationId: string }> }) {
  const { organizationId, workspaceId, integrationId } = await context.params;
  return withBffSession(request, false, (session) => runtime().api.getAwsTrustInstructions(session.accessToken, organizationId, workspaceId, integrationId));
}
