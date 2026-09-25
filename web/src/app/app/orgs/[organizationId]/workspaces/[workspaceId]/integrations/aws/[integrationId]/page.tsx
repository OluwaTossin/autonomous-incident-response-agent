import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { AwsIntegrationOnboarding } from "@/components/aws-integration-onboarding";
import { loadHostedPage, loadWorkspace, requireOrganization } from "@/lib/page-context";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export default async function AwsIntegrationPage({ params }: { params: Promise<{ organizationId: string; workspaceId: string; integrationId: string }> }) {
  const { organizationId, workspaceId, integrationId } = await params;
  const { session, bootstrap } = await loadHostedPage();
  const organization = requireOrganization(bootstrap.organizations, organizationId);
  const canManage = organization.permissions.includes("integration.manage");
  const [workspace, integration, trust] = await Promise.all([loadWorkspace(session.accessToken, organizationId, workspaceId), runtime().api.getAwsIntegration(session.accessToken, organizationId, workspaceId, integrationId), canManage ? runtime().api.getAwsTrustInstructions(session.accessToken, organizationId, workspaceId, integrationId) : Promise.resolve(undefined)]);
  return <AppShell organizations={bootstrap.organizations} organization={organization} workspace={workspace.workspace} user={session} csrfToken={session.csrfToken}><Link className="back-link" href={`/app/orgs/${organizationId}/workspaces/${workspaceId}/integrations`}><ArrowLeft aria-hidden="true" size={16} />Integrations</Link><div className="page-intro"><div><span className="eyebrow">AWS onboarding</span><h1>{integration.display_name}</h1></div><p>{integration.aws_account_id} · {integration.enabled_regions.join(", ")}</p></div><AwsIntegrationOnboarding initialIntegration={integration} trust={trust} organizationId={organizationId} workspaceId={workspaceId} csrfToken={session.csrfToken} canManage={canManage} /></AppShell>;
}
