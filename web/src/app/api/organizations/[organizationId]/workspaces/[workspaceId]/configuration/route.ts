import { NextRequest } from "next/server";
import { errorResponse, withBffSession } from "@/lib/bff";
import { runtime } from "@/lib/runtime";
import type { WorkspaceConfigurationUpdate } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function PATCH(request: NextRequest, context: { params: Promise<{ organizationId: string; workspaceId: string }> }) {
  const { organizationId, workspaceId } = await context.params;
  let body: WorkspaceConfigurationUpdate;
  try { body = (await request.json()) as WorkspaceConfigurationUpdate; }
  catch { return errorResponse(400, "validation", "A valid configuration update is required"); }
  if (!Number.isInteger(body.expected_version) || body.expected_version < 1) {
    return errorResponse(422, "validation", "A configuration version is required");
  }
  return withBffSession(request, true, (session) =>
    runtime().api.updateWorkspaceConfiguration(session.accessToken, organizationId, workspaceId, body),
  );
}
