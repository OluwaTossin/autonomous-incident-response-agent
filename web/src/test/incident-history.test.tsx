import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { RunInvestigation } from "@/components/run-investigation";
import type { TriageRun } from "@/lib/types";

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

describe("incident investigation", () => {
  it("renders result, attempt history, provenance, and feedback controls", () => {
    const html = renderToStaticMarkup(
      <RunInvestigation initialRun={run} organizationId="org-1" workspaceId="workspace-1" csrfToken="csrf" canOperate />,
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
  });

  it("does not expose mutation controls to read-only viewers", () => {
    const html = renderToStaticMarkup(
      <RunInvestigation initialRun={run} organizationId="org-1" workspaceId="workspace-1" csrfToken="csrf" canOperate={false} />,
    );
    expect(html).not.toContain("Operator feedback");
    expect(html).not.toContain("Cancel run");
  });
});
