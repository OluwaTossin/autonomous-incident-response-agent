import { ArrowRight, Cloud, Link2 } from "lucide-react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { AwsIntegrationCreate } from "@/components/aws-integration-create";
import { loadHostedPage, loadWorkspace, requireOrganization } from "@/lib/page-context";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export default async function IntegrationsPage({ params }: { params: Promise<{ organizationId: string; workspaceId: string }> }) {
  const { organizationId, workspaceId } = await params;
  const { session, bootstrap } = await loadHostedPage();
  const organization = requireOrganization(bootstrap.organizations, organizationId);
  const [workspace, page] = await Promise.all([loadWorkspace(session.accessToken, organizationId, workspaceId), runtime().api.listAwsIntegrations(session.accessToken, organizationId, workspaceId)]);
  const base = `/app/orgs/${organizationId}/workspaces/${workspaceId}/integrations/aws`;
  return <AppShell organizations={bootstrap.organizations} organization={organization} workspace={workspace.workspace} user={session} csrfToken={session.csrfToken}><div className="page-intro"><div><span className="eyebrow">Workspace connections</span><h1>Integrations</h1></div><p>Short-lived AssumeRole access with an AIRA-generated ExternalId. No customer access keys.</p></div><div className="integration-layout"><section className="integration-list-panel"><div className="section-title"><div><h2>AWS accounts</h2><p>Multiple account and role boundaries may be configured.</p></div><Cloud aria-hidden="true" size={20} /></div>{page.items.length ? <div className="integration-list">{page.items.map((item) => <Link key={item.integration_id} href={`${base}/${item.integration_id}`}><div><strong>{item.display_name}</strong><span>{item.aws_account_id} · {item.enabled_regions.join(", ")}</span></div><span className={`status-badge status-${item.state}`}>{item.state}</span><ArrowRight aria-hidden="true" size={17} /></Link>)}</div> : <div className="quiet-empty"><Link2 aria-hidden="true" size={18} />No AWS integrations are configured.</div>}</section>{organization.permissions.includes("integration.manage") ? <AwsIntegrationCreate organizationId={organizationId} workspaceId={workspaceId} csrfToken={session.csrfToken} /> : <aside className="integration-create"><div className="permission-note"><strong>Read-only integration access</strong><p>Your effective permissions do not include integration management.</p></div></aside>}</div></AppShell>;
}
