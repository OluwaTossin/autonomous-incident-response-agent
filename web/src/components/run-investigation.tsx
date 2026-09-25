"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { Ban, CheckCircle2, Clock3, LoaderCircle, Send, ShieldCheck, XCircle } from "lucide-react";
import type { ActionProposal, Approval, BrowserError, TriageRun } from "@/lib/types";

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);

export function RunInvestigation({
  initialRun,
  initialProposals,
  initialApprovals,
  organizationId,
  workspaceId,
  csrfToken,
  canOperate,
  canRequestApproval,
  canDecideApproval,
  userId,
}: {
  initialRun: TriageRun;
  initialProposals: ActionProposal[];
  initialApprovals: Record<string, Approval[]>;
  organizationId: string;
  workspaceId: string;
  csrfToken: string;
  canOperate: boolean;
  canRequestApproval: boolean;
  canDecideApproval: boolean;
  userId: string;
}) {
  const [run, setRun] = useState(initialRun);
  const [proposals, setProposals] = useState(initialProposals);
  const [approvals, setApprovals] = useState(initialApprovals);
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
            const nextProposals = (await proposalResponse.json()) as ActionProposal[];
            setProposals(nextProposals);
            const histories = await Promise.all(
              nextProposals.map(async (proposal) => {
                const response = await fetch(
                  `/api/action-proposals/${encodeURIComponent(proposal.action_proposal_id)}/approvals?${scope}`,
                  { cache: "no-store" },
                );
                return [proposal.action_proposal_id, response.ok ? await response.json() : []] as const;
              }),
            );
            setApprovals(Object.fromEntries(histories) as Record<string, Approval[]>);
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

  async function requestApproval(proposalId: string) {
    const approval = await mutate<Approval>(
      `/api/action-proposals/${encodeURIComponent(proposalId)}/approvals`,
      { organization_id: organizationId, workspace_id: workspaceId },
      csrfToken,
    );
    mergeApproval(approval);
  }

  async function decideApproval(approvalId: string, decision: "approve" | "reject" | "cancel", reason: string | null) {
    const approval = await mutate<Approval>(
      `/api/approvals/${encodeURIComponent(approvalId)}/${decision}`,
      { organization_id: organizationId, workspace_id: workspaceId, reason },
      csrfToken,
    );
    mergeApproval(approval);
  }

  function mergeApproval(approval: Approval) {
    setApprovals((current) => {
      const history = current[approval.action_proposal_id] || [];
      const next = history.some((item) => item.approval_id === approval.approval_id)
        ? history.map((item) => item.approval_id === approval.approval_id ? approval : item)
        : [approval, ...history];
      return { ...current, [approval.action_proposal_id]: next };
    });
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
      {run.state === "succeeded" ? <ActionProposals proposals={proposals} approvals={approvals} userId={userId} canRequest={canRequestApproval} canDecide={canDecideApproval} onRequest={requestApproval} onDecision={decideApproval} /> : null}
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

function ActionProposals({ proposals, approvals, userId, canRequest, canDecide, onRequest, onDecision }: { proposals: ActionProposal[]; approvals: Record<string, Approval[]>; userId: string; canRequest: boolean; canDecide: boolean; onRequest: (proposalId: string) => Promise<void>; onDecision: (approvalId: string, decision: "approve" | "reject" | "cancel", reason: string | null) => Promise<void> }) {
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
      <div className="proposal-parameters"><strong>Parameters</strong><pre>{JSON.stringify(proposal.parameters, null, 2)}</pre></div>
      <ApprovalPanel proposal={proposal} history={approvals[proposal.action_proposal_id] || []} userId={userId} canRequest={canRequest} canDecide={canDecide} onRequest={onRequest} onDecision={onDecision} />
    </article>)}</div> : <div className="quiet-empty">No controlled action proposals are available for this run.</div>}
  </section>;
}

function ApprovalPanel({ proposal, history, userId, canRequest, canDecide, onRequest, onDecision }: { proposal: ActionProposal; history: Approval[]; userId: string; canRequest: boolean; canDecide: boolean; onRequest: (proposalId: string) => Promise<void>; onDecision: (approvalId: string, decision: "approve" | "reject" | "cancel", reason: string | null) => Promise<void> }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const current = history[0];
  const eligible = proposal.policy_status === "allowed_for_review" && proposal.lifecycle_state === "ready_for_review";
  const pending = current?.state === "requested";
  const canAct = pending && canDecide && current.requested_by_id !== userId;
  const canCancel = pending && (canDecide || current.requested_by_id === userId);

  async function act(operation: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await operation();
      setReason("");
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(false);
    }
  }

  return <div className="approval-panel">
    <div className="approval-heading"><div><ShieldCheck aria-hidden="true" size={18} /><strong>Human approval</strong></div>{current ? <span className={`approval-state approval-${current.state}`}>{approvalLabel(current.state)}</span> : <span className="approval-state">Not requested</span>}</div>
    {current ? <dl className="approval-metadata">
      <div><dt>Requested</dt><dd>{formatTime(current.requested_at)}</dd></div>
      <div><dt>Expires</dt><dd>{formatTime(current.expires_at)}</dd></div>
      <div><dt>Requester</dt><dd>{current.requested_by_id}</dd></div>
      {current.decided_by_id ? <div><dt>Decided by</dt><dd>{current.decided_by_id}</dd></div> : null}
    </dl> : <p>Eligible proposals require a separate authorized human decision before any future execution intent can be created.</p>}
    {current?.decision_reason ? <p className="approval-reason"><strong>Decision reason</strong>{current.decision_reason}</p> : null}
    {pending && (canAct || canCancel) ? <label className="approval-reason-input">Decision reason<textarea value={reason} onChange={(event) => setReason(event.target.value)} maxLength={1000} rows={3} /></label> : null}
    <div className="approval-controls">
      {!pending && eligible && canRequest ? <button type="button" className="secondary-command" disabled={busy} onClick={() => void act(() => onRequest(proposal.action_proposal_id))}><Clock3 aria-hidden="true" size={16} />Request approval</button> : null}
      {canAct ? <button type="button" className="primary-command" disabled={busy} onClick={() => void act(() => onDecision(current.approval_id, "approve", reason.trim() || null))}><CheckCircle2 aria-hidden="true" size={16} />Approve for future execution</button> : null}
      {canAct ? <button type="button" className="secondary-command danger" disabled={busy || !reason.trim()} onClick={() => void act(() => onDecision(current.approval_id, "reject", reason.trim()))}><XCircle aria-hidden="true" size={16} />Reject</button> : null}
      {canCancel ? <button type="button" className="icon-command" disabled={busy} onClick={() => void act(() => onDecision(current.approval_id, "cancel", reason.trim() || null))}><Ban aria-hidden="true" size={16} />Cancel request</button> : null}
    </div>
    {history.length > 1 ? <details><summary>Approval history ({history.length})</summary><ol>{history.map((item) => <li key={item.approval_id}>{approvalLabel(item.state)} · {formatTime(item.updated_at)}</li>)}</ol></details> : null}
    {error ? <p className="form-error" role="alert">{error}</p> : null}
  </div>;
}

function approvalLabel(state: Approval["state"]): string {
  return {
    requested: "Approval requested",
    approved: "Approved for future execution",
    rejected: "Rejected",
    expired: "Expired",
    cancelled: "Cancelled",
  }[state];
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
