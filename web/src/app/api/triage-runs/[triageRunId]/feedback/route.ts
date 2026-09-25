import { NextRequest } from "next/server";
import { errorResponse, withBffSession } from "@/lib/bff";
import { runtime } from "@/lib/runtime";
import type { FeedbackCreate } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ triageRunId: string }> },
) {
  const body = (await request.json().catch(() => null)) as
    | (FeedbackCreate & { organization_id?: string; workspace_id?: string })
    | null;
  if (!body?.organization_id || !body.workspace_id) {
    return errorResponse(422, "validation", "Feedback scope is incomplete");
  }
  const { triageRunId } = await context.params;
  return withBffSession(request, true, (session) =>
    runtime().api.submitFeedback(
      session.accessToken,
      body.organization_id!,
      body.workspace_id!,
      triageRunId,
      {
        diagnosis_correct: body.diagnosis_correct,
        actions_useful: body.actions_useful,
        notes: body.notes,
      },
    ),
  );
}
