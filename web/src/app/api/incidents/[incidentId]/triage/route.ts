import { NextRequest } from "next/server";
import { errorResponse, withBffSession } from "@/lib/bff";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ incidentId: string }> },
) {
  const { incidentId } = await context.params;
  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return errorResponse(400, "validation", "A valid triage request is required");
  }
  const organizationId = stringValue(body.organization_id);
  const workspaceId = stringValue(body.workspace_id);
  const idempotencyKey = stringValue(body.idempotency_key);
  if (!organizationId || !workspaceId || !idempotencyKey) {
    return errorResponse(422, "validation", "Triage scope is incomplete");
  }
  return withBffSession(request, true, (session) =>
    runtime().api.requestTriage(
      session.accessToken,
      organizationId,
      workspaceId,
      incidentId,
      idempotencyKey,
    ),
  );
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}
