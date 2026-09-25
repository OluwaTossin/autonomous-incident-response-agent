import { NextRequest } from "next/server";
import { errorResponse, withBffSession } from "@/lib/bff";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ triageRunId: string }> },
) {
  const { triageRunId } = await context.params;
  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return errorResponse(400, "validation", "A valid cancellation request is required");
  }
  const organizationId = stringValue(body.organization_id);
  const workspaceId = stringValue(body.workspace_id);
  if (!organizationId || !workspaceId) {
    return errorResponse(422, "validation", "Triage scope is incomplete");
  }
  return withBffSession(request, true, (session) =>
    runtime().api.cancelTriage(
      session.accessToken,
      organizationId,
      workspaceId,
      triageRunId,
    ),
  );
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}
