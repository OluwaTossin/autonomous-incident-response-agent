import { Activity, ArrowRight, ListTree, Settings } from "lucide-react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { loadHostedPage, loadWorkspace, requireOrganization } from "@/lib/page-context";

export const dynamic = "force-dynamic";

export default async function WorkspacePage({ params }: { params: Promise<{ organizationId: string; workspaceId: string }> }) {
  const { organizationId, workspaceId } = await params;
  const { session, bootstrap } = await loadHostedPage();
  const organization = requireOrganization(bootstrap.organizations, organizationId);
  const detail = await loadWorkspace(session.accessToken, organizationId, workspaceId);
  const workspace = detail.workspace;
  const base = `/app/orgs/${organizationId}/workspaces/${workspaceId}`;
  return (
    <AppShell organizations={bootstrap.organizations} organization={organization} workspace={workspace} user={session} csrfToken={session.csrfToken}>
      <div className="page-intro"><div><span className="eyebrow">Active workspace</span><h1>{workspace.name}</h1></div><p>{workspace.description || "No workspace description has been added."}</p></div>
      <dl className="workspace-facts"><div><dt>Status</dt><dd>{workspace.state}</dd></div><div><dt>Your role</dt><dd>{organization.role}</dd></div><div><dt>Slug</dt><dd>{workspace.slug}</dd></div><div><dt>Updated</dt><dd>{new Date(workspace.updated_at).toLocaleString()}</dd></div></dl>
      <div className="action-list">
        <Link href={`${base}/incidents`}><ListTree aria-hidden="true" size={20} /><div><strong>Incident history</strong><span>Review durable incidents, triage runs, results, and evidence.</span></div><ArrowRight aria-hidden="true" size={18} /></Link>
        {organization.permissions.includes("incident.create") ? <Link href={`${base}/incidents/new`}><Activity aria-hidden="true" size={20} /><div><strong>Start incident triage</strong><span>Create a durable incident and queue an asynchronous run.</span></div><ArrowRight aria-hidden="true" size={18} /></Link> : <div className="disabled-action"><Activity aria-hidden="true" size={20} /><div><strong>Operational read only</strong><span>Your effective permissions do not allow incident creation.</span></div></div>}
        {organization.permissions.includes("workspace.update") ? <Link href={`${base}/settings`}><Settings aria-hidden="true" size={20} /><div><strong>Workspace settings</strong><span>Update metadata and allowlisted triage configuration.</span></div><ArrowRight aria-hidden="true" size={18} /></Link> : null}
      </div>
    </AppShell>
  );
}
