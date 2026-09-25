import { NextRequest } from "next/server";

export function executionIntentQueryScope(request: NextRequest) {
  const organizationId = request.nextUrl.searchParams.get("organization_id")?.trim();
  const workspaceId = request.nextUrl.searchParams.get("workspace_id")?.trim();
  return organizationId && workspaceId ? { organizationId, workspaceId } : null;
}

export async function executionIntentMutationBody(request: NextRequest, requireReason = false) {
  try {
    const body = (await request.json()) as Record<string, unknown>;
    const organizationId = stringValue(body.organization_id);
    const workspaceId = stringValue(body.workspace_id);
    const reason = stringValue(body.reason);
    if (!organizationId || !workspaceId || (requireReason && !reason)) return null;
    return { organizationId, workspaceId, reason };
  } catch {
    return null;
  }
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}
