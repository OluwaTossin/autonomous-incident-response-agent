import { NextRequest } from "next/server";
import { errorResponse, withBffSession } from "@/lib/bff";
import { executionIntentQueryScope } from "@/lib/execution-intent-bff";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest, context: { params: Promise<{ proposalId: string }> }) {
  const { proposalId } = await context.params;
  const scope = executionIntentQueryScope(request);
  if (!scope) return errorResponse(422, "validation", "Execution intent scope is incomplete");
  return withBffSession(request, false, (session) => runtime().api.listExecutionIntents(session.accessToken, scope.organizationId, scope.workspaceId, proposalId));
}
