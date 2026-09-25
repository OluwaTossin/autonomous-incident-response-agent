import { NextRequest } from "next/server";
import { errorResponse, withBffSession } from "@/lib/bff";
import { runtime } from "@/lib/runtime";
import type { AwsIntegrationUpdate } from "@/lib/types";

export const dynamic = "force-dynamic";

type Context = { params: Promise<{ organizationId: string; workspaceId: string; integrationId: string }> };

export async function GET(request: NextRequest, context: Context) {
  const { organizationId, workspaceId, integrationId } = await context.params;
  return withBffSession(request, false, (session) => runtime().api.getAwsIntegration(session.accessToken, organizationId, workspaceId, integrationId));
}

export async function PATCH(request: NextRequest, context: Context) {
  const { organizationId, workspaceId, integrationId } = await context.params;
  const body = (await request.json().catch(() => null)) as AwsIntegrationUpdate | null;
  if (!body || !Number.isInteger(body.expected_version)) return errorResponse(422, "validation", "Current integration version is required");
  return withBffSession(request, true, (session) => runtime().api.updateAwsIntegration(session.accessToken, organizationId, workspaceId, integrationId, body));
}
