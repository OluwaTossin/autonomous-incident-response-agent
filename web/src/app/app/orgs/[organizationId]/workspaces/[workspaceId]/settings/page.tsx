import { notFound } from "next/navigation";
import { AppShell } from "@/components/app-shell";
import { WorkspaceSettingsForm } from "@/components/workspace-settings-form";
import { loadHostedPage, loadWorkspace, requireOrganization } from "@/lib/page-context";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export default async function WorkspaceSettingsPage({ params }: { params: Promise<{ organizationId: string; workspaceId: string }> }) {
  const { organizationId, workspaceId } = await params;
  const { session, bootstrap } = await loadHostedPage();
  const organization = requireOrganization(bootstrap.organizations, organizationId);
  if (!organization.permissions.includes("workspace.update")) notFound();
  const detail = await loadWorkspace(session.accessToken, organizationId, workspaceId);
  const usage = organization.permissions.includes("usage.read")
    ? await runtime().api.getUsage(session.accessToken, organizationId, workspaceId)
    : null;
  return <AppShell organizations={bootstrap.organizations} organization={organization} workspace={detail.workspace} user={session} csrfToken={session.csrfToken}><div className="page-intro"><div><span className="eyebrow">Workspace administration</span><h1>Settings</h1></div><p>Changes use optimistic versions and durable actor-attributed audit events.</p></div><WorkspaceSettingsForm detail={detail} csrfToken={session.csrfToken} />{usage ? <section className="settings-section"><div className="section-heading"><div><span className="eyebrow">Operational capacity</span><h2>Usage and limits</h2></div></div><div className="table-wrap"><table><thead><tr><th>Limit</th><th>Used</th><th>Remaining</th><th>Status</th><th>Reset</th></tr></thead><tbody>{usage.quotas.map((quota) => <tr key={quota.quota_type}><td>{quota.quota_type.replaceAll("_", " ")}</td><td>{quota.current.toLocaleString()}</td><td>{quota.remaining.toLocaleString()}</td><td><span className={`status status-${quota.status}`}>{quota.status}</span></td><td>{quota.reset_at ? new Date(quota.reset_at).toISOString().slice(0, 16).replace("T", " ") + " UTC" : "No scheduled reset"}</td></tr>)}</tbody></table></div><p className="muted">These limits protect shared platform capacity. They are not billing or pricing.</p></section> : null}</AppShell>;
}
