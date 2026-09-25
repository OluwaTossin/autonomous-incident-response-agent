import { NextRequest } from "next/server";
import { errorResponse, withBffSession } from "@/lib/bff";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest, context: { params: Promise<{ organizationId: string; workspaceId: string }> }) {
  const { organizationId, workspaceId } = await context.params;
  let expectedVersion: number;
  try {
    const body = (await request.json()) as { expected_version?: number };
    expectedVersion = body.expected_version || 0;
  } catch { return errorResponse(400, "validation", "A valid archive request is required"); }
  if (!Number.isInteger(expectedVersion) || expectedVersion < 1) {
    return errorResponse(422, "validation", "A workspace version is required");
  }
  return withBffSession(request, true, (session) =>
    runtime().api.archiveWorkspace(session.accessToken, organizationId, workspaceId, expectedVersion),
  );
}
