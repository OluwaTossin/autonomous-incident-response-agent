import { NextRequest } from "next/server";
import { errorResponse, withBffSession } from "@/lib/bff";
import { runtime } from "@/lib/runtime";
import type { AwsIntegrationCreate } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest, context: { params: Promise<{ organizationId: string; workspaceId: string }> }) {
  const { organizationId, workspaceId } = await context.params;
  return withBffSession(request, false, (session) => runtime().api.listAwsIntegrations(session.accessToken, organizationId, workspaceId));
}

export async function POST(request: NextRequest, context: { params: Promise<{ organizationId: string; workspaceId: string }> }) {
  const { organizationId, workspaceId } = await context.params;
  const body = (await request.json().catch(() => null)) as AwsIntegrationCreate | null;
  if (!body?.display_name || !body.aws_account_id || !body.enabled_regions?.length) return errorResponse(422, "validation", "AWS account and regions are required");
  return withBffSession(request, true, (session) => runtime().api.createAwsIntegration(session.accessToken, organizationId, workspaceId, body));
}
