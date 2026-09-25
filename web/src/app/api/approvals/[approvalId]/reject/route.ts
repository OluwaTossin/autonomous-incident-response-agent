import { NextRequest } from "next/server";
import { approvalMutationBody } from "@/lib/approval-bff";
import { errorResponse, withBffSession } from "@/lib/bff";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest, context: { params: Promise<{ approvalId: string }> }) {
  const { approvalId } = await context.params;
  const body = await approvalMutationBody(request, true);
  if (!body) return errorResponse(422, "validation", "A rejection reason is required");
  return withBffSession(request, true, (session) => runtime().api.rejectApproval(session.accessToken, body.organizationId, body.workspaceId, approvalId, body.reason!));
}
