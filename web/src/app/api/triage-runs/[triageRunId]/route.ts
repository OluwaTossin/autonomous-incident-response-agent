import { NextRequest } from "next/server";
import { errorResponse, withBffSession } from "@/lib/bff";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ triageRunId: string }> },
) {
  const { triageRunId } = await context.params;
  const organizationId = request.nextUrl.searchParams.get("organization_id");
  const workspaceId = request.nextUrl.searchParams.get("workspace_id");
  if (!organizationId || !workspaceId) {
    return errorResponse(422, "validation", "Triage scope is incomplete");
  }
  return withBffSession(request, false, (session) =>
    runtime().api.getTriageRun(
      session.accessToken,
      organizationId,
      workspaceId,
      triageRunId,
    ),
  );
}
