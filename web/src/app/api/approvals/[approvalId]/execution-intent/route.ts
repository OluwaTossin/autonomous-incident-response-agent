import { NextRequest } from "next/server";
import { errorResponse, withBffSession } from "@/lib/bff";
import { executionIntentMutationBody } from "@/lib/execution-intent-bff";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest, context: { params: Promise<{ approvalId: string }> }) {
  const { approvalId } = await context.params;
  const body = await executionIntentMutationBody(request);
  if (!body) return errorResponse(422, "validation", "Execution intent scope is incomplete");
  return withBffSession(request, true, (session) => runtime().api.prepareExecutionIntent(session.accessToken, body.organizationId, body.workspaceId, approvalId));
}
