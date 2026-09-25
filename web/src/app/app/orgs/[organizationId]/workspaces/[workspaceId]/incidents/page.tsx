import { Activity, ArrowRight, Filter, Plus } from "lucide-react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { loadHostedPage, loadWorkspace, requireOrganization } from "@/lib/page-context";
import { runtime } from "@/lib/runtime";

export const dynamic = "force-dynamic";

export default async function IncidentsPage({
  params,
  searchParams,
}: {
  params: Promise<{ organizationId: string; workspaceId: string }>;
  searchParams: Promise<{ cursor?: string; state?: string; created_from?: string; created_to?: string }>;
}) {
  const { organizationId, workspaceId } = await params;
  const filters = await searchParams;
  const { session, bootstrap } = await loadHostedPage();
  const organization = requireOrganization(bootstrap.organizations, organizationId);
  const detail = await loadWorkspace(session.accessToken, organizationId, workspaceId);
  const query = new URLSearchParams({ limit: "25" });
  for (const key of ["cursor", "state", "created_from", "created_to"] as const) {
    if (filters[key]) query.set(key, normalizeDate(key, filters[key]!));
  }
  const page = await runtime().api.listIncidents(session.accessToken, organizationId, workspaceId, query.toString());
  const base = `/app/orgs/${organizationId}/workspaces/${workspaceId}/incidents`;
  return <AppShell organizations={bootstrap.organizations} organization={organization} workspace={detail.workspace} user={session} csrfToken={session.csrfToken}>
    <div className="page-intro"><div><span className="eyebrow">Investigation history</span><h1>Incidents</h1></div>{organization.permissions.includes("incident.create") ? <Link className="primary-command" href={`${base}/new`}><Plus aria-hidden="true" size={17} />New incident</Link> : null}</div>
    <form className="history-filters">
      <label>State<select name="state" defaultValue={filters.state || ""}><option value="">All states</option><option value="open">Open</option><option value="investigating">Investigating</option><option value="resolved">Resolved</option><option value="closed">Closed</option></select></label>
      <label>Created after<input type="date" name="created_from" defaultValue={filters.created_from || ""} /></label>
      <label>Created before<input type="date" name="created_to" defaultValue={filters.created_to || ""} /></label>
      <button className="icon-command" type="submit"><Filter aria-hidden="true" size={16} />Apply filters</button>
    </form>
    {page.items.length ? <div className="incident-table" role="list">
      {page.items.map((incident) => <Link role="listitem" key={incident.incident_id} href={`${base}/${incident.incident_id}`}>
        <div><strong>{incident.title}</strong><span>{incident.service_name} · {incident.environment}</span></div>
        <div><span className={`severity severity-${(incident.latest_severity || incident.severity_hint || "low").toLowerCase()}`}>{incident.latest_severity || incident.severity_hint || "UNRATED"}</span><small>{incident.source_provider} / {incident.source_type}</small></div>
        <div><span className="status-badge">{incident.state}</span><small>{incident.latest_triage_state || "Not triaged"} · {incident.triage_run_count} run{incident.triage_run_count === 1 ? "" : "s"}</small></div>
        <time dateTime={incident.created_at}>{new Date(incident.created_at).toLocaleString()}</time><ArrowRight aria-hidden="true" size={17} />
      </Link>)}
    </div> : <div className="empty-state"><Activity aria-hidden="true" size={22} /><div><h2>No incidents found</h2><p>Adjust the filters or create the first incident in this workspace.</p></div></div>}
    {page.next_cursor ? <Link className="pagination-link" href={`${base}?${nextQuery(filters, page.next_cursor)}`}>Older incidents <ArrowRight aria-hidden="true" size={16} /></Link> : null}
  </AppShell>;
}

function normalizeDate(key: string, value: string): string {
  if (key === "created_from") return `${value}T00:00:00Z`;
  if (key === "created_to") return `${value}T23:59:59.999Z`;
  return value;
}
function nextQuery(filters: Record<string, string | undefined>, cursor: string): string {
  const query = new URLSearchParams({ cursor });
  for (const key of ["state", "created_from", "created_to"]) if (filters[key]) query.set(key, filters[key]!);
  return query.toString();
}
