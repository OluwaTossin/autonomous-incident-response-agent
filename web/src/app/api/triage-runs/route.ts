import { NextRequest } from "next/server";
import { errorResponse, withBffSession } from "@/lib/bff";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const organizationId = request.nextUrl.searchParams.get("organization_id");
  const workspaceId = request.nextUrl.searchParams.get("workspace_id");
  if (!organizationId || !workspaceId) {
    return errorResponse(422, "validation", "Triage scope is incomplete");
  }
  const query = new URLSearchParams(request.nextUrl.searchParams);
  query.delete("organization_id");
  query.delete("workspace_id");
  return withBffSession(request, false, (session) =>
    runtime().api.listTriageRuns(
      session.accessToken,
      organizationId,
      workspaceId,
      query.toString(),
    ),
  );
}
