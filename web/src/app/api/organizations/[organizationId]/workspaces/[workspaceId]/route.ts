import { NextRequest } from "next/server";
import { errorResponse, withBffSession } from "@/lib/bff";
import { runtime } from "@/lib/runtime";
import type { WorkspaceMetadataUpdate } from "@/lib/types";

export const dynamic = "force-dynamic";
type Context = { params: Promise<{ organizationId: string; workspaceId: string }> };

export async function GET(request: NextRequest, context: Context) {
  const { organizationId, workspaceId } = await context.params;
  return withBffSession(request, false, (session) =>
    runtime().api.getWorkspace(session.accessToken, organizationId, workspaceId),
  );
}

export async function PATCH(request: NextRequest, context: Context) {
  const { organizationId, workspaceId } = await context.params;
  let body: WorkspaceMetadataUpdate;
  try { body = (await request.json()) as WorkspaceMetadataUpdate; }
  catch { return errorResponse(400, "validation", "A valid workspace update is required"); }
  if (!Number.isInteger(body.expected_version) || body.expected_version < 1) {
    return errorResponse(422, "validation", "A workspace version is required");
  }
  return withBffSession(request, true, (session) =>
    runtime().api.updateWorkspace(session.accessToken, organizationId, workspaceId, body),
  );
}
