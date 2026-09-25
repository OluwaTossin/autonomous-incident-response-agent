import { Activity, Building2, CircleUserRound, ListTree, Plug, Settings } from "lucide-react";
import Link from "next/link";
import { LogoutButton } from "./logout-button";
import type { BootstrapOrganization, BootstrapWorkspace } from "@/lib/types";

export function AppShell({
  children,
  organizations,
  organization,
  workspace,
  user,
  csrfToken,
}: {
  children: React.ReactNode;
  organizations: BootstrapOrganization[];
  organization?: BootstrapOrganization;
  workspace?: BootstrapWorkspace & { state?: string };
  user: { displayName: string; email: string };
  csrfToken: string;
}) {
  const workspaceBase = organization && workspace
    ? `/app/orgs/${organization.organization_id}/workspaces/${workspace.workspace_id}`
    : null;
  return (
    <div className="app-frame">
      <header className="app-header">
        <Link className="identity-group brand-link" href="/app">
          <span className="brand-mark compact" aria-hidden="true">A</span>
          <span><strong>AIRA</strong><small>Hosted operations</small></span>
        </Link>
        <nav aria-label="Primary navigation">
          <Link href="/app"><Building2 aria-hidden="true" size={17} />Organizations</Link>
          {workspaceBase ? <Link href={`${workspaceBase}/incidents`}><ListTree aria-hidden="true" size={17} />Incidents</Link> : null}
          {workspaceBase && organization?.permissions.includes("incident.create") ? <Link href={`${workspaceBase}/incidents/new`}><Activity aria-hidden="true" size={17} />New triage</Link> : null}
          {workspaceBase ? <Link href={`${workspaceBase}/integrations`}><Plug aria-hidden="true" size={17} />Integrations</Link> : null}
          {workspaceBase && organization?.permissions.includes("workspace.update") ? (
            <Link href={`${workspaceBase}/settings`}><Settings aria-hidden="true" size={17} />Settings</Link>
          ) : null}
        </nav>
        <div className="user-group">
          <CircleUserRound aria-hidden="true" size={21} />
          <div><strong>{user.displayName}</strong><span>{user.email}</span></div>
          <LogoutButton csrfToken={csrfToken} />
        </div>
      </header>
      {organization ? (
        <div className="context-bar">
          <div><span>Organization</span><strong>{organization.name}</strong><small>{organization.role} · {organization.membership_state} membership</small></div>
          {workspace ? <div><span>Workspace</span><strong>{workspace.name}</strong><small>{workspace.state || "active"}</small></div> : null}
          <div className="context-switcher" aria-label="Authorized organizations">
            {organizations.map((item) => (
              <Link key={item.organization_id} aria-current={item.organization_id === organization.organization_id ? "page" : undefined} href={`/app/orgs/${item.organization_id}/workspaces`}>
                {item.name}
              </Link>
            ))}
          </div>
        </div>
      ) : null}
      <main className="app-main">{children}</main>
    </div>
  );
}
