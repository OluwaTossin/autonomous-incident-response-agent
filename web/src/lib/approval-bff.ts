import "server-only";

export async function approvalMutationBody(request: Request, reasonRequired: boolean) {
  try {
    const body = (await request.json()) as Record<string, unknown>;
    const organizationId = stringValue(body.organization_id);
    const workspaceId = stringValue(body.workspace_id);
    const reason = nullableReason(body.reason);
    if (!organizationId || !workspaceId || (reasonRequired && !reason)) return null;
    return { organizationId, workspaceId, reason };
  } catch {
    return null;
  }
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function nullableReason(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  return normalized && normalized.length <= 1000 ? normalized : null;
}
