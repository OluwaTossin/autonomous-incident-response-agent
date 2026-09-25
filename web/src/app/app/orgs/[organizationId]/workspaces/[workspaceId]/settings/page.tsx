import { notFound } from "next/navigation";
import { AppShell } from "@/components/app-shell";
import { WorkspaceSettingsForm } from "@/components/workspace-settings-form";
import { loadHostedPage, loadWorkspace, requireOrganization } from "@/lib/page-context";

export const dynamic = "force-dynamic";

export default async function WorkspaceSettingsPage({ params }: { params: Promise<{ organizationId: string; workspaceId: string }> }) {
  const { organizationId, workspaceId } = await params;
  const { session, bootstrap } = await loadHostedPage();
  const organization = requireOrganization(bootstrap.organizations, organizationId);
  if (!organization.permissions.includes("workspace.update")) notFound();
  const detail = await loadWorkspace(session.accessToken, organizationId, workspaceId);
  return <AppShell organizations={bootstrap.organizations} organization={organization} workspace={detail.workspace} user={session} csrfToken={session.csrfToken}><div className="page-intro"><div><span className="eyebrow">Workspace administration</span><h1>Settings</h1></div><p>Changes use optimistic versions and durable actor-attributed audit events.</p></div><WorkspaceSettingsForm detail={detail} csrfToken={session.csrfToken} /></AppShell>;
}
