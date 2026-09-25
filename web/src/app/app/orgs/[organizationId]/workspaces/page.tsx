import { ArrowRight, Boxes, Plus } from "lucide-react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { WorkspaceCreateForm } from "@/components/workspace-create-form";
import { loadHostedPage, requireOrganization } from "@/lib/page-context";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export default async function WorkspacesPage({ params, searchParams }: { params: Promise<{ organizationId: string }>; searchParams: Promise<{ cursor?: string; archived?: string }> }) {
  const { organizationId } = await params;
  const query = await searchParams;
  const { session, bootstrap } = await loadHostedPage();
  const organization = requireOrganization(bootstrap.organizations, organizationId);
  const page = await runtime().api.listWorkspaces(session.accessToken, organizationId, query.cursor);
  const canCreate = organization.permissions.includes("workspace.create");
  return (
    <AppShell organizations={bootstrap.organizations} organization={organization} user={session} csrfToken={session.csrfToken}>
      <div className="page-intro"><div><span className="eyebrow">{organization.role} access</span><h1>Workspaces</h1></div><p>Operational boundaries within {organization.name}. Every selection is re-authorized by the backend.</p></div>
      {query.archived ? <div className="inline-notice" role="status">Workspace archived. Historical records remain durable.</div> : null}
      <div className="workspace-layout">
        <section aria-labelledby="workspace-list-title"><div className="section-title"><div><h2 id="workspace-list-title">Available workspaces</h2><p>{page.items.length ? "Choose where you want to work." : "No accessible active workspaces."}</p></div><Boxes aria-hidden="true" size={21} /></div>
          {page.items.length ? <div className="workspace-list">{page.items.map((workspace) => <Link href={`/app/orgs/${organizationId}/workspaces/${workspace.workspace_id}`} key={workspace.workspace_id}><div><strong>{workspace.name}</strong><span>{workspace.description || workspace.slug}</span></div><span className="status-badge">{workspace.state}</span><ArrowRight aria-hidden="true" size={18} /></Link>)}</div> : <div className="quiet-empty"><Boxes aria-hidden="true" size={22} /><p>{canCreate ? "Create the first workspace for this organization." : "You do not have access to a workspace yet."}</p></div>}
          {page.next_cursor ? <Link className="pagination-link" href={`?cursor=${encodeURIComponent(page.next_cursor)}`}>Next workspaces <ArrowRight aria-hidden="true" size={16} /></Link> : null}
        </section>
        <aside className="create-panel">{canCreate ? <><div className="section-title"><div><h2>Create workspace</h2><p>Use a stable name and URL slug.</p></div><Plus aria-hidden="true" size={21} /></div><WorkspaceCreateForm organizationId={organizationId} csrfToken={session.csrfToken} /></> : <div className="permission-note"><strong>Read-only workspace access</strong><p>Your effective permissions do not include workspace creation.</p></div>}</aside>
      </div>
    </AppShell>
  );
}
