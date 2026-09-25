import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { RunInvestigation } from "@/components/run-investigation";
import type { ActionProposal, Approval, ExecutionIntent, TriageRun } from "@/lib/types";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

const run: TriageRun = {
  triage_run_id: "run-1",
  triage_id: "run-1",
  incident_id: "incident-1",
  job_id: "job-1",
  state: "succeeded",
  job_state: "succeeded",
  cancellation_requested: false,
  attempt_count: 2,
  max_attempts: 3,
  next_attempt_at: null,
  created_at: "2026-09-25T12:00:00Z",
  started_at: "2026-09-25T12:00:01Z",
  completed_at: "2026-09-25T12:00:05Z",
  failure_code: null,
  failure_category: null,
  failure_summary: null,
  result: {
    incident_summary: "Checkout latency breached its objective.",
    severity: "HIGH",
    likely_root_cause: "Dependency timeout",
    recommended_actions: ["Inspect dependency saturation"],
    escalate: true,
    confidence: 0.82,
    evidence: [],
    timeline: ["Alert received", "Triage completed"],
    triage_id: "run-1",
  },
  evidence: [{
    sequence: 0,
    type: "runbook",
    source: "checkout.md",
    reason: "Documents timeout recovery",
    origin: "tenant",
    document_id: "doc-1",
    document_version_id: "version-2",
    knowledge_index_version_id: "index-3",
    chunk_index: 4,
    score: 0.91,
  }],
  operational_context: {
    snapshot_id: "snapshot-1",
    integration_id: "integration-1",
    provider: "aws.cloudwatch",
    region: "eu-west-2",
    status: "partial",
    window_start: "2026-09-25T11:45:00Z",
    window_end: "2026-09-25T12:02:00Z",
    collected_at: "2026-09-25T12:00:02Z",
    policy_version: "cloudwatch-context-v1",
    truncated: true,
    diagnostics: [{ collector: "logs", status: "succeeded", code: null, summary: null }],
    items: [{
      sequence: 0,
      type: "aws_cloudwatch_log",
      source: "/aws/lambda/checkout:stream",
      observed_at: "2026-09-25T12:00:00Z",
      content: { message: "redacted timeout" },
      truncated: false,
    }],
  },
};

const proposals: ActionProposal[] = [{
  action_proposal_id: "proposal-1",
  incident_id: "incident-1",
  triage_run_id: "run-1",
  proposal_type: "manual_investigation",
  target: {
    type: "incident",
    identifier: "incident-1",
    provider: "aira",
    provenance: "incident",
    integration_id: null,
    account_id: null,
    region: null,
  },
  summary: "Manual investigation",
  rationale: "Derived deterministically from the completed triage recommendation.",
  parameters: { schema_version: 1, instruction: "Inspect dependency saturation" },
  risk_level: "low",
  reversibility: "unknown",
  policy_status: "manual_only",
  policy_reason: "manual_guidance",
  lifecycle_state: "manual_only",
  source_result_version: 1,
  source_result_hash: "a".repeat(64),
  proposal_schema_version: 1,
  created_by_type: "system",
  created_at: "2026-09-25T12:00:05Z",
}];

const eligibleProposal: ActionProposal = {
  ...proposals[0],
  proposal_type: "acknowledge_incident",
  summary: "Acknowledge the incident",
  parameters: { schema_version: 1 },
  reversibility: "reversible",
  policy_status: "allowed_for_review",
  policy_reason: "ready_for_review",
  lifecycle_state: "ready_for_review",
};

const pendingApproval: Approval = {
  approval_id: "approval-1",
  action_proposal_id: "proposal-1",
  state: "requested",
  state_version: 1,
  proposal_schema_version: 1,
  source_result_version: 1,
  source_result_hash: "a".repeat(64),
  normalized_action_hash: "b".repeat(64),
  requested_by_type: "human",
  requested_by_id: "requester-1",
  requested_at: "2026-09-25T12:01:00Z",
  expires_at: "2026-09-25T12:31:00Z",
  decided_by_type: null,
  decided_by_id: null,
  decided_at: null,
  decision_reason: null,
  created_at: "2026-09-25T12:01:00Z",
  updated_at: "2026-09-25T12:01:00Z",
};

const approvedApproval: Approval = {
  ...pendingApproval,
  state: "approved",
  state_version: 2,
  decided_by_type: "human",
  decided_by_id: "admin-1",
  decided_at: "2026-09-25T12:02:00Z",
  updated_at: "2026-09-25T12:02:00Z",
};

const intent: ExecutionIntent = {
  execution_intent_id: "intent-1",
  action_proposal_id: "proposal-1",
  approval_id: "approval-1",
  incident_id: "incident-1",
  triage_run_id: "run-1",
  lifecycle_state: "prepared",
  connector_kind: "internal",
  operation_kind: "acknowledge_incident",
  provider: "aira",
  target: eligibleProposal.target,
  parameters: { schema_version: 1 },
  request_schema_version: 1,
  proposal_schema_version: 1,
  source_result_version: 1,
  source_result_hash: "a".repeat(64),
  normalized_action_hash: "b".repeat(64),
  approval_state_version: 2,
  approval_binding_hash: "c".repeat(64),
  intent_hash: "d".repeat(64),
  risk_level: "low",
  reversibility: "reversible",
  policy_version: 1,
  approved_by_type: "human",
  approved_by_id: "admin-1",
  approved_at: "2026-09-25T12:02:00Z",
  created_by_type: "human",
  created_at: "2026-09-25T12:03:00Z",
  updated_at: "2026-09-25T12:03:00Z",
  execute_before: "2026-09-25T12:33:00Z",
  terminal_at: null,
  terminal_reason: null,
  validation_status: "passed",
  execution_status: "not_executed",
};

describe("incident investigation", () => {
  it("renders result, attempt history, provenance, and feedback controls", () => {
    const html = renderToStaticMarkup(
      <RunInvestigation initialRun={run} initialProposals={proposals} initialApprovals={{}} initialIntents={{}} organizationId="org-1" workspaceId="workspace-1" csrfToken="csrf" canOperate canRequestApproval canDecideApproval canPrepareIntent canCancelIntent userId="admin-1" />,
    );
    expect(html).toContain("2 / 3");
    expect(html).toContain("Dependency timeout");
    expect(html).toContain("doc-1");
    expect(html).toContain("version-2");
    expect(html).toContain("0.910");
    expect(html).toContain("Operator feedback");
    expect(html).toContain("CloudWatch context");
    expect(html).toContain("redacted timeout");
    expect(html).toContain("truncated");
    expect(html).toContain("Proposed actions");
    expect(html).toContain("Manual only");
    expect(html).toContain("No action has been executed");
    expect(html).not.toContain("Approve");
    expect(html).not.toContain("Execute");
  });

  it("does not expose mutation controls to read-only viewers", () => {
    const html = renderToStaticMarkup(
      <RunInvestigation initialRun={run} initialProposals={proposals} initialApprovals={{}} initialIntents={{}} organizationId="org-1" workspaceId="workspace-1" csrfToken="csrf" canOperate={false} canRequestApproval={false} canDecideApproval={false} canPrepareIntent={false} canCancelIntent={false} userId="viewer-1" />,
    );
    expect(html).not.toContain("Operator feedback");
    expect(html).not.toContain("Cancel run");
  });

  it("shows an exact pending approval decision without execution controls", () => {
    const html = renderToStaticMarkup(
      <RunInvestigation initialRun={run} initialProposals={[eligibleProposal]} initialApprovals={{ "proposal-1": [pendingApproval] }} initialIntents={{}} organizationId="org-1" workspaceId="workspace-1" csrfToken="csrf" canOperate canRequestApproval canDecideApproval canPrepareIntent canCancelIntent userId="admin-1" />,
    );
    expect(html).toContain("Approval requested");
    expect(html).toContain("Approve for future execution");
    expect(html).toContain("Reject");
    expect(html).toContain("Parameters");
    expect(html).not.toContain(">Execute<");
  });

  it.each(["approved", "rejected", "expired", "cancelled"] as const)("renders %s approval history as a durable decision", (state) => {
    const approval = {
      ...pendingApproval,
      state,
      decided_by_type: state === "expired" ? null : "human" as const,
      decided_by_id: state === "expired" ? null : "admin-1",
      decided_at: "2026-09-25T12:02:00Z",
      decision_reason: state === "rejected" ? "Target changed" : null,
    };
    const html = renderToStaticMarkup(
      <RunInvestigation initialRun={run} initialProposals={[eligibleProposal]} initialApprovals={{ "proposal-1": [approval] }} initialIntents={{}} organizationId="org-1" workspaceId="workspace-1" csrfToken="csrf" canOperate canRequestApproval canDecideApproval canPrepareIntent canCancelIntent userId="admin-1" />,
    );
    expect(html).toContain({ approved: "Approved for future execution", rejected: "Rejected", expired: "Expired", cancelled: "Cancelled" }[state]);
    expect(html).not.toContain(">Execute<");
  });

  it("shows the exact frozen intent and never offers execution", () => {
    const html = renderToStaticMarkup(
      <RunInvestigation initialRun={run} initialProposals={[eligibleProposal]} initialApprovals={{ "proposal-1": [approvedApproval] }} initialIntents={{ "proposal-1": [intent] }} organizationId="org-1" workspaceId="workspace-1" csrfToken="csrf" canOperate canRequestApproval canDecideApproval canPrepareIntent canCancelIntent userId="admin-1" />,
    );
    expect(html).toContain("Execution intent prepared");
    expect(html).toContain("Approved action frozen for controlled execution");
    expect(html).toContain("Connector validation passed");
    expect(html).toContain("Not executed");
    expect(html).toContain("d".repeat(64));
    expect(html).toContain("Cancel intent");
    expect(html).not.toMatch(/>Execute</);
    expect(html).not.toMatch(/>Run</);
    expect(html).not.toMatch(/>Apply</);
    expect(html).not.toMatch(/>Remediate</);
  });
});
