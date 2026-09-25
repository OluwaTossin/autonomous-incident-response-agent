import { NextRequest } from "next/server";
import { errorResponse, withBffSession } from "@/lib/bff";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest, context: { params: Promise<{ organizationId: string; workspaceId: string; integrationId: string }> }) {
  const { organizationId, workspaceId, integrationId } = await context.params;
  const body = (await request.json().catch(() => null)) as { expected_version?: number } | null;
  if (!body || !Number.isInteger(body.expected_version)) return errorResponse(422, "validation", "Current integration version is required");
  return withBffSession(request, true, (session) => runtime().api.disableAwsIntegration(session.accessToken, organizationId, workspaceId, integrationId, body.expected_version!));
}
