import { NextRequest } from "next/server";
import { errorResponse, withBffSession } from "@/lib/bff";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest, context: { params: Promise<{ proposalId: string }> }) {
  const { proposalId } = await context.params;
  const scope = queryScope(request);
  if (!scope) return errorResponse(422, "validation", "Approval scope is incomplete");
  return withBffSession(request, false, (session) => runtime().api.listApprovals(session.accessToken, scope.organizationId, scope.workspaceId, proposalId));
}

export async function POST(request: NextRequest, context: { params: Promise<{ proposalId: string }> }) {
  const { proposalId } = await context.params;
  const body = await requestBody(request);
  if (!body) return errorResponse(422, "validation", "Approval scope is incomplete");
  return withBffSession(request, true, (session) => runtime().api.requestApproval(session.accessToken, body.organizationId, body.workspaceId, proposalId));
}

function queryScope(request: NextRequest) {
  const organizationId = request.nextUrl.searchParams.get("organization_id");
  const workspaceId = request.nextUrl.searchParams.get("workspace_id");
  return organizationId && workspaceId ? { organizationId, workspaceId } : null;
}

async function requestBody(request: NextRequest) {
  try {
    const body = (await request.json()) as Record<string, unknown>;
    const organizationId = stringValue(body.organization_id);
    const workspaceId = stringValue(body.workspace_id);
    return organizationId && workspaceId ? { organizationId, workspaceId } : null;
  } catch {
    return null;
  }
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}
