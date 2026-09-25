import { Activity, CircleUserRound } from "lucide-react";
import { redirect } from "next/navigation";
import { IncidentWorkflow } from "@/components/incident-workflow";
import { LogoutButton } from "@/components/logout-button";
import { HostedApiError } from "@/lib/api-client";
import { requireBrowserSession } from "@/lib/protected-session";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function HostedAppPage() {
  const session = await requireBrowserSession();
  let bootstrap;
  try {
    bootstrap = await runtime().api.bootstrap(session.accessToken);
  } catch (error) {
    if (error instanceof HostedApiError && error.status === 401) {
      redirect("/auth/login?returnTo=%2Fapp");
    }
    return (
      <main className="fatal-page">
        <h1>AIRA is temporarily unavailable</h1>
        <p>The hosted API could not load your authorized workspace context.</p>
      </main>
    );
  }
  return (
    <div className="app-frame">
      <header className="app-header">
        <div className="identity-group">
          <div className="brand-mark compact" aria-hidden="true">A</div>
          <div><strong>AIRA</strong><span>Hosted operations</span></div>
        </div>
        <nav aria-label="Primary navigation">
          <a className="active" href="/app"><Activity aria-hidden="true" size={17} />Triage</a>
        </nav>
        <div className="user-group">
          <CircleUserRound aria-hidden="true" size={21} />
          <div><strong>{session.displayName}</strong><span>{session.email}</span></div>
          <LogoutButton csrfToken={session.csrfToken} />
        </div>
      </header>
      <main className="app-main">
        <div className="page-intro">
          <div><span className="eyebrow">Operations desk</span><h1>Incident triage</h1></div>
          <p>Create a durable incident and follow the backend-owned run state to completion.</p>
        </div>
        <IncidentWorkflow
          organizations={bootstrap.organizations}
          csrfToken={session.csrfToken}
        />
      </main>
    </div>
  );
}
