import { NextRequest } from "next/server";
import { errorResponse, withBffSession } from "@/lib/bff";
import { runtime } from "@/lib/runtime";
import type { WorkspaceCreate } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest, context: { params: Promise<{ organizationId: string }> }) {
  const { organizationId } = await context.params;
  const cursor = request.nextUrl.searchParams.get("cursor") || undefined;
  return withBffSession(request, false, (session) =>
    runtime().api.listWorkspaces(session.accessToken, organizationId, cursor),
  );
}

export async function POST(request: NextRequest, context: { params: Promise<{ organizationId: string }> }) {
  const { organizationId } = await context.params;
  let body: WorkspaceCreate;
  try { body = (await request.json()) as WorkspaceCreate; }
  catch { return errorResponse(400, "validation", "A valid workspace is required"); }
  if (!text(body.name) || !text(body.slug)) {
    return errorResponse(422, "validation", "Workspace name and slug are required");
  }
  return withBffSession(request, true, (session) =>
    runtime().api.createWorkspace(session.accessToken, organizationId, body),
  );
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}
