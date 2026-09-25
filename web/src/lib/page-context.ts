import "server-only";

import { notFound, redirect } from "next/navigation";
import { HostedApiError } from "./api-client";
import { requireBrowserSession } from "./protected-session";
import { runtime } from "./runtime";
import type { BootstrapOrganization, WorkspaceDetail } from "./types";

export async function loadHostedPage() {
  const session = await requireBrowserSession();
  try {
    return { session, bootstrap: await runtime().api.bootstrap(session.accessToken) };
  } catch (error) {
    if (error instanceof HostedApiError && error.status === 401) redirect("/auth/login?returnTo=%2Fapp");
    throw error;
  }
}

export function requireOrganization(
  organizations: BootstrapOrganization[],
  organizationId: string,
): BootstrapOrganization {
  const organization = organizations.find((item) => item.organization_id === organizationId);
  if (!organization) notFound();
  return organization;
}

export async function loadWorkspace(
  accessToken: string,
  organizationId: string,
  workspaceId: string,
): Promise<WorkspaceDetail> {
  try {
    return await runtime().api.getWorkspace(accessToken, organizationId, workspaceId);
  } catch (error) {
    if (error instanceof HostedApiError && error.status === 401) redirect("/auth/login?returnTo=%2Fapp");
    if (error instanceof HostedApiError && (error.status === 403 || error.status === 404)) notFound();
    throw error;
  }
}
