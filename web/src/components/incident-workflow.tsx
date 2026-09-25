"use client";

import React, { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Ban, CircleAlert, LoaderCircle, Play, Send } from "lucide-react";
import type {
  BootstrapOrganization,
  BrowserError,
  Incident,
  IncidentCreate,
  TriageAccepted,
  TriageRun,
} from "@/lib/types";

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

export interface IncidentDraft {
  title: string;
  description: string;
  service_name: string;
  environment: string;
  severity_hint: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
}

export function validateIncidentDraft(draft: IncidentDraft): string | null {
  if (!draft.title.trim()) return "Incident title is required.";
  if (!draft.description.trim()) return "Describe the observed behavior.";
  if (!draft.service_name.trim()) return "Service name is required.";
  if (!draft.environment.trim()) return "Environment is required.";
  return null;
}

export function IncidentWorkflow({
  organizations,
  csrfToken,
}: {
  organizations: BootstrapOrganization[];
  csrfToken: string;
}) {
  const firstOrganization = organizations[0];
  const [organizationId, setOrganizationId] = useState(
    firstOrganization?.organization_id || "",
  );
  const organization = useMemo(
    () => organizations.find((item) => item.organization_id === organizationId),
    [organizationId, organizations],
  );
  const [workspaceId, setWorkspaceId] = useState(
    firstOrganization?.workspaces[0]?.workspace_id || "",
  );
  const [draft, setDraft] = useState<IncidentDraft>({
    title: "",
    description: "",
    service_name: "",
    environment: "production",
    severity_hint: "HIGH",
  });
  const [incident, setIncident] = useState<Incident | null>(null);
  const [accepted, setAccepted] = useState<TriageAccepted | null>(null);
  const [run, setRun] = useState<TriageRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stopped = useRef(false);

  useEffect(() => {
    const next = organization?.workspaces[0]?.workspace_id || "";
    if (!organization?.workspaces.some((item) => item.workspace_id === workspaceId)) {
      setWorkspaceId(next);
    }
  }, [organization, workspaceId]);

  useEffect(() => {
    if (!accepted || (run && TERMINAL.has(run.state))) return;
    stopped.current = false;
    let delay = 2_000;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      if (stopped.current) return;
      if (document.visibilityState === "hidden") {
        timer = setTimeout(poll, delay);
        return;
      }
      try {
        const response = await fetch(
          `/api/triage-runs/${encodeURIComponent(accepted.triage_run_id)}` +
            `?organization_id=${encodeURIComponent(organizationId)}` +
            `&workspace_id=${encodeURIComponent(workspaceId)}`,
          { cache: "no-store" },
        );
        if (response.status === 401) return reauthenticate();
        const payload = (await response.json()) as TriageRun | BrowserError;
        if (!response.ok) throw new Error(errorMessage(payload));
        const next = payload as TriageRun;
        setRun(next);
        if (TERMINAL.has(next.state)) return;
        delay = Math.min(Math.round(delay * 1.5), 8_000);
        timer = setTimeout(poll, delay);
      } catch (pollError) {
        setError(message(pollError));
      }
    };
    timer = setTimeout(poll, delay);
    return () => {
      stopped.current = true;
      if (timer) clearTimeout(timer);
    };
  }, [accepted, organizationId, run, workspaceId]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const validation = validateIncidentDraft(draft);
    if (validation) return setError(validation);
    if (!organizationId || !workspaceId) return setError("Select an available workspace.");
    setBusy(true);
    setError(null);
    setIncident(null);
    setAccepted(null);
    setRun(null);
    try {
      const input: IncidentCreate = {
        ...draft,
        title: draft.title.trim(),
        description: draft.description.trim(),
        service_name: draft.service_name.trim(),
        environment: draft.environment.trim(),
        source_provider: "aira-web",
        source_type: "manual",
        observed_at: new Date().toISOString(),
      };
      const created = await browserRequest<Incident>("/api/incidents", csrfToken, {
        organization_id: organizationId,
        workspace_id: workspaceId,
        incident: input,
      });
      setIncident(created);
      const queued = await browserRequest<TriageAccepted>(
        `/api/incidents/${encodeURIComponent(created.incident_id)}/triage`,
        csrfToken,
        {
          organization_id: organizationId,
          workspace_id: workspaceId,
          idempotency_key: crypto.randomUUID(),
        },
      );
      setAccepted(queued);
    } catch (submitError) {
      setError(message(submitError));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!accepted) return;
    try {
      const next = await browserRequest<TriageRun>(
        `/api/triage-runs/${encodeURIComponent(accepted.triage_run_id)}/cancel`,
        csrfToken,
        { organization_id: organizationId, workspace_id: workspaceId },
      );
      setRun(next);
    } catch (cancelError) {
      setError(message(cancelError));
    }
  }

  if (!organizations.length) {
    return (
      <section className="empty-state" aria-labelledby="no-access-title">
        <CircleAlert aria-hidden="true" size={22} />
        <div>
          <h2 id="no-access-title">No active workspace access</h2>
          <p>An organization owner must grant you access before you can triage incidents.</p>
        </div>
      </section>
    );
  }

  return (
    <div className="workflow-grid">
      <section className="work-panel" aria-labelledby="new-incident-title">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Manual intake</span>
            <h2 id="new-incident-title">Create and triage an incident</h2>
          </div>
          <Send aria-hidden="true" size={21} />
        </div>
        <form onSubmit={submit} className="incident-form">
          <div className="field-row">
            <label>
              Organization
              <select
                value={organizationId}
                onChange={(event) => setOrganizationId(event.target.value)}
              >
                {organizations.map((item) => (
                  <option value={item.organization_id} key={item.organization_id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Workspace
              <select
                value={workspaceId}
                onChange={(event) => setWorkspaceId(event.target.value)}
              >
                {(organization?.workspaces || []).map((item) => (
                  <option value={item.workspace_id} key={item.workspace_id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label>
            Incident title
            <input
              value={draft.title}
              maxLength={200}
              onChange={(event) => setDraft({ ...draft, title: event.target.value })}
              placeholder="Checkout latency above objective"
            />
          </label>
          <label>
            Observed behavior
            <textarea
              value={draft.description}
              maxLength={4000}
              rows={5}
              onChange={(event) => setDraft({ ...draft, description: event.target.value })}
              placeholder="Describe the signal, impact, and timing."
            />
          </label>
          <div className="field-row">
            <label>
              Service
              <input
                value={draft.service_name}
                maxLength={200}
                onChange={(event) => setDraft({ ...draft, service_name: event.target.value })}
                placeholder="checkout-api"
              />
            </label>
            <label>
              Environment
              <input
                value={draft.environment}
                maxLength={80}
                onChange={(event) => setDraft({ ...draft, environment: event.target.value })}
              />
            </label>
          </div>
          <label>
            Severity hint
            <select
              value={draft.severity_hint}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  severity_hint: event.target.value as IncidentDraft["severity_hint"],
                })
              }
            >
              {(["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const).map((severity) => (
                <option value={severity} key={severity}>{severity}</option>
              ))}
            </select>
          </label>
          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <button className="primary-command" type="submit" disabled={busy || !workspaceId}>
            {busy ? <LoaderCircle className="spin" aria-hidden="true" size={18} /> : <Play aria-hidden="true" size={18} />}
            {busy ? "Submitting" : "Start triage"}
          </button>
        </form>
      </section>

      <section className="result-panel" aria-live="polite" aria-labelledby="run-title">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Async run</span>
            <h2 id="run-title">Triage status</h2>
          </div>
          {accepted && !TERMINAL.has(run?.state || accepted.state) ? (
            <button className="icon-command danger" type="button" onClick={() => void cancel()}>
              <Ban aria-hidden="true" size={17} /><span>Cancel</span>
            </button>
          ) : null}
        </div>
        {!accepted ? (
          <div className="quiet-state">Submit an incident to begin a durable triage run.</div>
        ) : (
          <RunView incident={incident} accepted={accepted} run={run} />
        )}
      </section>
    </div>
  );
}

export function RunView({
  incident,
  accepted,
  run,
}: {
  incident: Incident | null;
  accepted: TriageAccepted;
  run: TriageRun | null;
}) {
  const state = run?.state || accepted.state;
  return (
    <div className="run-content">
      <div className={`status-line status-${state}`}>
        {!TERMINAL.has(state) ? <LoaderCircle className="spin" aria-hidden="true" size={17} /> : null}
        <strong>{state}</strong>
        <span>{incident?.title}</span>
      </div>
      <dl className="run-metadata">
        <div><dt>Triage ID</dt><dd>{accepted.triage_id}</dd></div>
        <div><dt>Job</dt><dd>{run?.job_state || accepted.job_state}</dd></div>
      </dl>
      {run?.failure_summary ? (
        <div className="failure-state" role="alert">
          <strong>Triage failed</strong><p>{run.failure_summary}</p>
        </div>
      ) : null}
      {run?.result ? (
        <div className="triage-result">
          <div className="result-lead">
            <span className={`severity severity-${run.result.severity.toLowerCase()}`}>
              {run.result.severity}
            </span>
            <span>{Math.round(run.result.confidence * 100)}% confidence</span>
          </div>
          <h3>{run.result.likely_root_cause}</h3>
          <p>{run.result.incident_summary}</p>
          <h4>Recommended actions</h4>
          <ol>{run.result.recommended_actions.map((action) => <li key={action}>{action}</li>)}</ol>
          <h4>Evidence</h4>
          <div className="evidence-list">
            {run.evidence.map((item) => (
              <article key={`${item.sequence}-${item.source}`}>
                <strong>{item.source}</strong><p>{item.reason}</p>
              </article>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

async function browserRequest<T>(url: string, csrfToken: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json", "x-csrf-token": csrfToken },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (response.status === 401) {
    reauthenticate();
    throw new Error("Your session expired. Redirecting to sign in.");
  }
  const payload = (await response.json()) as T | BrowserError;
  if (!response.ok) throw new Error(errorMessage(payload));
  return payload as T;
}

function errorMessage(payload: unknown): string {
  if (payload && typeof payload === "object" && "error" in payload) {
    const error = (payload as BrowserError).error;
    if (error?.message) return error.message;
  }
  return "The request could not be completed.";
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : "The request could not be completed.";
}

function reauthenticate(): void {
  window.location.assign("/auth/login?returnTo=%2Fapp");
}
