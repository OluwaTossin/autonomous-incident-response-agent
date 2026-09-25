import { notFound } from "next/navigation";
import { AppShell } from "@/components/app-shell";
import { IncidentWorkflow } from "@/components/incident-workflow";
import { loadHostedPage, loadWorkspace, requireOrganization } from "@/lib/page-context";

export const dynamic = "force-dynamic";

export default async function NewIncidentPage({ params }: { params: Promise<{ organizationId: string; workspaceId: string }> }) {
  const { organizationId, workspaceId } = await params;
  const { session, bootstrap } = await loadHostedPage();
  const organization = requireOrganization(bootstrap.organizations, organizationId);
  if (!organization.permissions.includes("incident.create")) notFound();
  const detail = await loadWorkspace(session.accessToken, organizationId, workspaceId);
  return <AppShell organizations={bootstrap.organizations} organization={organization} workspace={detail.workspace} user={session} csrfToken={session.csrfToken}><div className="page-intro"><div><span className="eyebrow">{detail.workspace.name}</span><h1>Incident triage</h1></div><p>Create a durable incident and follow the backend-owned run state to completion.</p></div><IncidentWorkflow organizationId={organizationId} workspaceId={workspaceId} csrfToken={session.csrfToken} /></AppShell>;
}
