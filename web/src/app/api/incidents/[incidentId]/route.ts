import { NextRequest } from "next/server";
import { errorResponse, withBffSession } from "@/lib/bff";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ incidentId: string }> },
) {
  const scope = readScope(request);
  if (!scope) return errorResponse(422, "validation", "Incident scope is incomplete");
  const { incidentId } = await context.params;
  return withBffSession(request, false, (session) =>
    runtime().api.getIncident(
      session.accessToken,
      scope.organizationId,
      scope.workspaceId,
      incidentId,
    ),
  );
}

export async function PATCH(
  request: NextRequest,
  context: { params: Promise<{ incidentId: string }> },
) {
  const scope = readScope(request);
  if (!scope) return errorResponse(422, "validation", "Incident scope is incomplete");
  const body = (await request.json().catch(() => null)) as { state?: unknown } | null;
  if (!body || !["investigating", "resolved", "closed"].includes(String(body.state))) {
    return errorResponse(422, "validation", "Select a valid incident state");
  }
  const { incidentId } = await context.params;
  return withBffSession(request, true, (session) =>
    runtime().api.transitionIncident(
      session.accessToken,
      scope.organizationId,
      scope.workspaceId,
      incidentId,
      body.state as "investigating" | "resolved" | "closed",
    ),
  );
}

function readScope(request: NextRequest) {
  const organizationId = request.nextUrl.searchParams.get("organization_id");
  const workspaceId = request.nextUrl.searchParams.get("workspace_id");
  return organizationId && workspaceId ? { organizationId, workspaceId } : null;
}
