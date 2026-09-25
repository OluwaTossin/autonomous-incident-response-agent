"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { Ban, CheckCircle2, LoaderCircle, Send } from "lucide-react";
import type { ActionProposal, BrowserError, TriageRun } from "@/lib/types";

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

export function RunInvestigation({
  initialRun,
  initialProposals,
  organizationId,
  workspaceId,
  csrfToken,
  canOperate,
}: {
  initialRun: TriageRun;
  initialProposals: ActionProposal[];
  organizationId: string;
  workspaceId: string;
  csrfToken: string;
  canOperate: boolean;
}) {
  const [run, setRun] = useState(initialRun);
  const [proposals, setProposals] = useState(initialProposals);
  const [error, setError] = useState<string | null>(null);
  const [feedbackSent, setFeedbackSent] = useState(false);
  const stopped = useRef(false);
  const scope = `organization_id=${encodeURIComponent(organizationId)}&workspace_id=${encodeURIComponent(workspaceId)}`;

  useEffect(() => {
    if (TERMINAL.has(run.state)) return;
    stopped.current = false;
    let delay = 2_000;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (stopped.current) return;
      if (document.visibilityState === "hidden") {
        timer = setTimeout(poll, delay);
        return;
      }
      try {
        const response = await fetch(`/api/triage-runs/${encodeURIComponent(run.triage_run_id)}?${scope}`, { cache: "no-store" });
        if (response.status === 401) return window.location.assign("/auth/login?returnTo=%2Fapp");
        const payload = (await response.json()) as TriageRun | BrowserError;
        if (!response.ok) throw new Error(errorMessage(payload));
        const next = payload as TriageRun;
        setRun(next);
        if (next.state === "succeeded") {
          const proposalResponse = await fetch(
            `/api/triage-runs/${encodeURIComponent(run.triage_run_id)}/action-proposals?${scope}`,
            { cache: "no-store" },
          );
          if (proposalResponse.ok) {
            setProposals((await proposalResponse.json()) as ActionProposal[]);
          }
        } else if (!TERMINAL.has(next.state)) {
          delay = Math.min(Math.round(delay * 1.5), 8_000);
          timer = setTimeout(poll, delay);
        }
      } catch (caught) {
        setError(message(caught));
      }
    };
    timer = setTimeout(poll, delay);
    return () => {
      stopped.current = true;
      clearTimeout(timer);
    };
  }, [run.state, run.triage_run_id, scope]);

  async function cancel() {
    try {
      setRun(await mutate<TriageRun>(
        `/api/triage-runs/${encodeURIComponent(run.triage_run_id)}/cancel`,
        { organization_id: organizationId, workspace_id: workspaceId },
        csrfToken,
      ));
    } catch (caught) {
      setError(message(caught));
    }
  }

  async function feedback(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await mutate(
        `/api/triage-runs/${encodeURIComponent(run.triage_run_id)}/feedback`,
        {
          organization_id: organizationId,
          workspace_id: workspaceId,
          diagnosis_correct: nullableBoolean(form.get("diagnosis_correct")),
          actions_useful: nullableBoolean(form.get("actions_useful")),
          notes: String(form.get("notes") || "").trim() || null,
        },
        csrfToken,
      );
      setFeedbackSent(true);
    } catch (caught) {
      setError(message(caught));
    }
  }

  return (
    <div className="investigation-stack">
      <section className="run-summary">
        <div className={`status-line status-${run.state}`}>
          {!TERMINAL.has(run.state) ? <LoaderCircle className="spin" aria-hidden="true" size={17} /> : null}
          <strong>{run.state}</strong><span>Job {run.job_state}</span>
        </div>
        <dl className="run-metadata">
          <div><dt>Triage ID</dt><dd>{run.triage_id}</dd></div>
          <div><dt>Attempts</dt><dd>{run.attempt_count ?? 0} / {run.max_attempts ?? 0}</dd></div>
          <div><dt>Started</dt><dd>{formatTime(run.started_at)}</dd></div>
          <div><dt>Completed</dt><dd>{formatTime(run.completed_at)}</dd></div>
        </dl>
        {run.next_attempt_at ? <p className="inline-notice">Retry scheduled for {formatTime(run.next_attempt_at)}.</p> : null}
        {run.failure_summary ? <div className="failure-state" role="alert"><strong>{run.failure_category || "Failure"}</strong><p>{run.failure_summary}</p></div> : null}
        {canOperate && !TERMINAL.has(run.state) ? <button className="icon-command danger" type="button" onClick={() => void cancel()}><Ban aria-hidden="true" size={17} />Cancel run</button> : null}
      </section>
      {run.operational_context ? <OperationalContext run={run} /> : null}
      {run.result ? <Result run={run} /> : <section className="quiet-empty"><LoaderCircle className="spin" aria-hidden="true" size={18} />Triage output is not available yet.</section>}
      {run.state === "succeeded" ? <ActionProposals proposals={proposals} /> : null}
      {run.state === "succeeded" && canOperate ? (
        <section className="feedback-panel">
          <div className="section-title"><div><h2>Operator feedback</h2><p>Record whether the diagnosis and actions helped this investigation.</p></div><Send aria-hidden="true" size={19} /></div>
          {feedbackSent ? <div className="quiet-empty"><CheckCircle2 aria-hidden="true" size={18} />Feedback recorded.</div> : (
            <form className="feedback-form" onSubmit={feedback}>
              <label>Diagnosis <select name="diagnosis_correct" defaultValue=""><option value="">Not assessed</option><option value="true">Correct</option><option value="false">Incorrect</option></select></label>
              <label>Actions <select name="actions_useful" defaultValue=""><option value="">Not assessed</option><option value="true">Useful</option><option value="false">Not useful</option></select></label>
              <label className="feedback-notes">Notes<textarea name="notes" maxLength={2000} rows={4} /></label>
              <button className="primary-command" type="submit"><Send aria-hidden="true" size={16} />Submit feedback</button>
            </form>
          )}
        </section>
      ) : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
    </div>
  );
}

function ActionProposals({ proposals }: { proposals: ActionProposal[] }) {
  return <section className="action-proposals" aria-labelledby="action-proposals-title">
    <div className="section-title"><div><h2 id="action-proposals-title">Proposed actions</h2><p>Policy-evaluated recommendations for operator review. No action has been executed.</p></div></div>
    {proposals.length ? <div className="proposal-list">{proposals.map((proposal) => <article key={proposal.action_proposal_id}>
      <div className="proposal-heading"><div><span className="eyebrow">Proposed action</span><h3>{proposal.summary}</h3></div><span className={`proposal-status proposal-${proposal.policy_status}`}>{policyLabel(proposal.policy_status)}</span></div>
      <p>{proposal.rationale}</p>
      <dl className="provenance">
        <div><dt>Type</dt><dd>{humanize(proposal.proposal_type)}</dd></div>
        <div><dt>Target</dt><dd>{proposal.target.identifier}</dd></div>
        <div><dt>Risk</dt><dd>{humanize(proposal.risk_level)}</dd></div>
        <div><dt>Reversibility</dt><dd>{humanize(proposal.reversibility)}</dd></div>
        <div><dt>Policy</dt><dd>{humanize(proposal.policy_reason)}</dd></div>
        <div><dt>Source</dt><dd>Triage result v{proposal.source_result_version}</dd></div>
      </dl>
    </article>)}</div> : <div className="quiet-empty">No controlled action proposals are available for this run.</div>}
  </section>;
}

function policyLabel(value: ActionProposal["policy_status"]): string {
  if (value === "allowed_for_review") return "Requires review";
  if (value === "manual_only") return "Manual only";
  return "Blocked by policy";
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function OperationalContext({ run }: { run: TriageRun }) {
  const context = run.operational_context!;
  const metrics = context.items.filter((item) => item.type === "aws_cloudwatch_metric");
  const logs = context.items.filter((item) => item.type === "aws_cloudwatch_log");
  return <section className="operational-context">
    <div className="section-title"><div><h2>CloudWatch context</h2><p>Redacted, bounded evidence collected for this run.</p></div><span className={`context-status context-${context.status}`}>{context.status}</span></div>
    <dl className="run-metadata">
      <div><dt>Region</dt><dd>{context.region}</dd></div>
      <div><dt>Window</dt><dd>{formatTime(context.window_start)} to {formatTime(context.window_end)}</dd></div>
      <div><dt>Metrics</dt><dd>{metrics.length}</dd></div>
      <div><dt>Log events</dt><dd>{logs.length}{context.truncated ? " (truncated)" : ""}</dd></div>
    </dl>
    <div className="collector-list">{context.diagnostics.map((item) => <div key={item.collector}><strong>{item.collector}</strong><span>{item.status}</span>{item.summary ? <p>{item.summary}</p> : null}</div>)}</div>
    {metrics.length ? <div className="context-items"><h3>Alarm metrics</h3>{metrics.map((item) => <article key={item.sequence}><strong>{String(item.content.metric_name || "Alarm metric")}</strong><span>{Array.isArray(item.content.points) ? item.content.points.length : 0} datapoints</span></article>)}</div> : null}
    {logs.length ? <div className="context-items"><h3>Log excerpts</h3>{logs.map((item) => <article key={item.sequence}><strong>{item.source}</strong><p>{String(item.content.message || "")}</p></article>)}</div> : null}
  </section>;
}

function Result({ run }: { run: TriageRun }) {
  const result = run.result!;
  return <section className="triage-result investigation-result">
    <div className="result-lead"><span className={`severity severity-${result.severity.toLowerCase()}`}>{result.severity}</span><span>{Math.round(result.confidence * 100)}% confidence</span><span>{result.service_name || "Service not identified"}</span><span>{result.escalate ? "Escalation recommended" : "No escalation recommended"}</span></div>
    <h2>{result.likely_root_cause}</h2><p>{result.incident_summary}</p>
    {result.conflicting_signals_summary ? <><h3>Conflicting signals</h3><p>{result.conflicting_signals_summary}</p></> : null}
    <h3>Recommended actions</h3><ol>{result.recommended_actions.map((action) => <li key={action}>{action}</li>)}</ol>
    <h3>Evidence and provenance</h3>
    <div className="evidence-list">{run.evidence.map((item) => <article key={`${item.sequence}-${item.source}`}><strong>{item.sequence + 1}. {item.source}</strong><span className="eyebrow">{item.type}</span><p>{item.reason}</p><dl className="provenance"><div><dt>Origin</dt><dd>{item.origin || "runtime"}</dd></div><div><dt>Document</dt><dd>{item.document_id || "Not applicable"}</dd></div><div><dt>Version</dt><dd>{item.document_version_id || "Not applicable"}</dd></div><div><dt>Index</dt><dd>{item.knowledge_index_version_id || "Not applicable"}</dd></div><div><dt>Chunk</dt><dd>{item.chunk_index ?? "Not applicable"}</dd></div><div><dt>Score</dt><dd>{item.score === null ? "Not applicable" : item.score.toFixed(3)}</dd></div></dl></article>)}</div>
    {result.timeline.length ? <><h3>Timeline</h3><ol>{result.timeline.map((entry) => <li key={entry}>{entry}</li>)}</ol></> : null}
  </section>;
}

async function mutate<T>(url: string, body: unknown, csrfToken: string): Promise<T> {
  const response = await fetch(url, { method: "POST", headers: { "content-type": "application/json", "x-csrf-token": csrfToken }, body: JSON.stringify(body), cache: "no-store" });
  const payload = (await response.json()) as T | BrowserError;
  if (!response.ok) throw new Error(errorMessage(payload));
  return payload as T;
}
function nullableBoolean(value: FormDataEntryValue | null): boolean | null { return value === "true" ? true : value === "false" ? false : null; }
function formatTime(value: string | null): string { return value ? new Date(value).toLocaleString() : "Not yet"; }
function errorMessage(payload: unknown): string { return payload && typeof payload === "object" && "error" in payload ? (payload as BrowserError).error.message : "The request could not be completed."; }
function message(error: unknown): string { return error instanceof Error ? error.message : "The request could not be completed."; }
