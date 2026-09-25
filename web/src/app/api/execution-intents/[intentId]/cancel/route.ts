import { NextRequest } from "next/server";
import { errorResponse, withBffSession } from "@/lib/bff";
import { executionIntentMutationBody } from "@/lib/execution-intent-bff";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest, context: { params: Promise<{ intentId: string }> }) {
  const { intentId } = await context.params;
  const body = await executionIntentMutationBody(request, true);
  if (!body || !body.reason) return errorResponse(422, "validation", "Execution intent cancellation is invalid");
  const reason = body.reason;
  return withBffSession(request, true, (session) => runtime().api.cancelExecutionIntent(session.accessToken, body.organizationId, body.workspaceId, intentId, reason));
}
