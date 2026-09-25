import { NextRequest } from "next/server";
import { approvalMutationBody } from "@/lib/approval-bff";
import { errorResponse, withBffSession } from "@/lib/bff";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest, context: { params: Promise<{ approvalId: string }> }) {
  const { approvalId } = await context.params;
  const body = await approvalMutationBody(request, false);
  if (!body) return errorResponse(422, "validation", "Approval request is invalid");
  return withBffSession(request, true, (session) => runtime().api.cancelApproval(session.accessToken, body.organizationId, body.workspaceId, approvalId, body.reason));
}
