import { Building2, ChevronRight } from "lucide-react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { loadHostedPage } from "@/lib/page-context";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function HostedAppPage() {
  const { session, bootstrap } = await loadHostedPage();
  return (
    <AppShell organizations={bootstrap.organizations} user={session} csrfToken={session.csrfToken}>
      <div className="page-intro"><div><span className="eyebrow">Authorized access</span><h1>Organizations</h1></div><p>Select an organization to view the workspaces the backend currently authorizes.</p></div>
      {!bootstrap.organizations.length ? (
        <section className="empty-state"><Building2 aria-hidden="true" size={22} /><div><h2>No active organizations</h2><p>An AIRA administrator must provision or activate your membership.</p></div></section>
      ) : (
        <div className="organization-list">
          {bootstrap.organizations.map((organization) => (
            <Link href={`/app/orgs/${organization.organization_id}/workspaces`} key={organization.organization_id}>
              <div><strong>{organization.name}</strong><span>{organization.slug}</span></div>
              <div><span className="role-badge">{organization.role}</span><small>{organization.workspaces.length} visible workspaces</small></div>
              <ChevronRight aria-hidden="true" size={19} />
            </Link>
          ))}
        </div>
      )}
    </AppShell>
  );
}
