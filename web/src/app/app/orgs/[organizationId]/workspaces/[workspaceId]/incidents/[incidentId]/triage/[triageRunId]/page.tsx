import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { RunInvestigation } from "@/components/run-investigation";
import { loadHostedPage, loadWorkspace, requireOrganization } from "@/lib/page-context";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export default async function TriageRunPage({ params }: { params: Promise<{ organizationId: string; workspaceId: string; incidentId: string; triageRunId: string }> }) {
  const { organizationId, workspaceId, incidentId, triageRunId } = await params;
  const { session, bootstrap } = await loadHostedPage();
  const organization = requireOrganization(bootstrap.organizations, organizationId);
  const [workspace, incident, run, proposals] = await Promise.all([
    loadWorkspace(session.accessToken, organizationId, workspaceId),
    runtime().api.getIncident(session.accessToken, organizationId, workspaceId, incidentId),
    runtime().api.getTriageRun(session.accessToken, organizationId, workspaceId, triageRunId),
    runtime().api.listActionProposals(session.accessToken, organizationId, workspaceId, triageRunId),
  ]);
  const approvalEntries = await Promise.all(
    proposals.map(async (proposal) => [
      proposal.action_proposal_id,
      await runtime().api.listApprovals(
        session.accessToken,
        organizationId,
        workspaceId,
        proposal.action_proposal_id,
      ),
    ] as const),
  );
  const approvals = Object.fromEntries(approvalEntries);
  const intentEntries = await Promise.all(
    proposals.map(async (proposal) => [
      proposal.action_proposal_id,
      await runtime().api.listExecutionIntents(
        session.accessToken,
        organizationId,
        workspaceId,
        proposal.action_proposal_id,
      ),
    ] as const),
  );
  const intents = Object.fromEntries(intentEntries);
  const incidentHref = `/app/orgs/${organizationId}/workspaces/${workspaceId}/incidents/${incidentId}`;
  return <AppShell organizations={bootstrap.organizations} organization={organization} workspace={workspace.workspace} user={session} csrfToken={session.csrfToken}>
    <Link className="back-link" href={incidentHref}><ArrowLeft aria-hidden="true" size={16} />{incident.title}</Link>
    <div className="page-intro"><div><span className="eyebrow">Triage investigation</span><h1>Run {run.triage_id.slice(0, 8)}</h1></div><p>Durable result, evidence provenance, and operator controls for this run.</p></div>
    <RunInvestigation initialRun={run} initialProposals={proposals} initialApprovals={approvals} initialIntents={intents} organizationId={organizationId} workspaceId={workspaceId} csrfToken={session.csrfToken} canOperate={organization.permissions.includes("incident.create")} canRequestApproval={organization.permissions.includes("approval.request")} canDecideApproval={organization.permissions.includes("approval.decide")} canPrepareIntent={organization.permissions.includes("execution_intent.prepare")} canCancelIntent={organization.permissions.includes("execution_intent.cancel")} userId={bootstrap.user_id} />
  </AppShell>;
}
