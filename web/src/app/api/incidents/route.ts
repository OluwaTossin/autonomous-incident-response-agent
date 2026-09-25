import { NextRequest } from "next/server";
import { errorResponse, withBffSession } from "@/lib/bff";
import { runtime } from "@/lib/runtime";
import type { IncidentCreate } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return errorResponse(400, "validation", "A valid incident is required");
  }
  const organizationId = stringValue(body.organization_id);
  const workspaceId = stringValue(body.workspace_id);
  const incident = body.incident as IncidentCreate | undefined;
  if (!organizationId || !workspaceId || !validIncident(incident)) {
    return errorResponse(422, "validation", "Complete all required incident fields");
  }
  return withBffSession(request, true, (session) =>
    runtime().api.createIncident(
      session.accessToken,
      organizationId,
      workspaceId,
      incident,
    ),
  );
}

function validIncident(value: IncidentCreate | undefined): value is IncidentCreate {
  return Boolean(
    value &&
      stringValue(value.title) &&
      stringValue(value.description) &&
      stringValue(value.service_name) &&
      stringValue(value.environment) &&
      stringValue(value.source_provider) &&
      stringValue(value.source_type) &&
      stringValue(value.observed_at),
  );
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}
