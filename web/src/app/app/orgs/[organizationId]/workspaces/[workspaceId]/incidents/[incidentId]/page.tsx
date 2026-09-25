import { ArrowLeft, ArrowRight, Clock3 } from "lucide-react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { IncidentActions } from "@/components/incident-actions";
import { loadHostedPage, loadWorkspace, requireOrganization } from "@/lib/page-context";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export default async function IncidentDetailPage({ params }: { params: Promise<{ organizationId: string; workspaceId: string; incidentId: string }> }) {
  const { organizationId, workspaceId, incidentId } = await params;
  const { session, bootstrap } = await loadHostedPage();
  const organization = requireOrganization(bootstrap.organizations, organizationId);
  const [workspace, incident, runs] = await Promise.all([
    loadWorkspace(session.accessToken, organizationId, workspaceId),
    runtime().api.getIncident(session.accessToken, organizationId, workspaceId, incidentId),
    runtime().api.listTriageRuns(session.accessToken, organizationId, workspaceId, new URLSearchParams({ incident_id: incidentId, limit: "50" }).toString()),
  ]);
  const base = `/app/orgs/${organizationId}/workspaces/${workspaceId}/incidents`;
  const canOperate = organization.permissions.includes("incident.create");
  return <AppShell organizations={bootstrap.organizations} organization={organization} workspace={workspace.workspace} user={session} csrfToken={session.csrfToken}>
    <Link className="back-link" href={base}><ArrowLeft aria-hidden="true" size={16} />Incident history</Link>
    <div className="page-intro"><div><span className="eyebrow">{incident.service_name} · {incident.environment}</span><h1>{incident.title}</h1></div>{canOperate ? <IncidentActions organizationId={organizationId} workspaceId={workspaceId} incidentId={incidentId} state={incident.state} csrfToken={session.csrfToken} /> : null}</div>
    <dl className="incident-facts"><div><dt>State</dt><dd>{incident.state}</dd></div><div><dt>Observed</dt><dd>{new Date(incident.observed_at).toLocaleString()}</dd></div><div><dt>Created</dt><dd>{new Date(incident.created_at).toLocaleString()}</dd></div><div><dt>Source</dt><dd>{incident.source_provider} / {incident.source_type}</dd></div><div><dt>Severity hint</dt><dd>{incident.severity_hint || "None"}</dd></div></dl>
    <section className="incident-context"><h2>Observed behavior</h2><p>{incident.description}</p>{incident.metric_summary ? <><h3>Metric summary</h3><p>{incident.metric_summary}</p></> : null}</section>
    <section className="history-section"><div className="section-title"><div><h2>Triage history</h2><p>Newest run first. Retries remain part of the same run; a new operator request creates a distinct run.</p></div><Clock3 aria-hidden="true" size={20} /></div>
      {runs.items.length ? <div className="run-list">{runs.items.map((run, index) => <Link href={`${base}/${incidentId}/triage/${run.triage_run_id}`} key={run.triage_run_id}><div><strong>{index === 0 ? "Latest run" : `Earlier run ${runs.items.length - index}`}</strong><span>{run.triage_id}</span></div><div><span className={`status-badge status-${run.state}`}>{run.state}</span><small>{run.severity || "No result"}{run.confidence !== null ? ` · ${Math.round(run.confidence * 100)}%` : ""}</small></div><div><span>{new Date(run.created_at).toLocaleString()}</span><small>Attempts {run.attempt_count}/{run.max_attempts}</small></div><ArrowRight aria-hidden="true" size={17} /></Link>)}</div> : <div className="quiet-empty">No triage runs have been requested for this incident.</div>}
    </section>
  </AppShell>;
}
