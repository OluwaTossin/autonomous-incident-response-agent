import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  RunView,
  validateIncidentDraft,
  type IncidentDraft,
} from "@/components/incident-workflow";
import type { TriageAccepted, TriageRun } from "@/lib/types";

const draft: IncidentDraft = {
  title: "Latency",
  description: "p95 is above objective",
  service_name: "checkout",
  environment: "production",
  severity_hint: "HIGH",
};
const accepted: TriageAccepted = {
  triage_run_id: "run-1",
  triage_id: "run-1",
  incident_id: "incident-1",
  job_id: "job-1",
  state: "queued",
  job_state: "pending",
  created_at: "2026-09-25T12:00:00Z",
};

function run(state: string): TriageRun {
  return {
    ...accepted,
    state,
    job_state: state === "succeeded" ? "succeeded" : "running",
    cancellation_requested: false,
    started_at: "2026-09-25T12:00:02Z",
    completed_at: state === "succeeded" ? "2026-09-25T12:00:08Z" : null,
    failure_code: state === "failed" ? "provider_failed" : null,
    failure_category: state === "failed" ? "transient" : null,
    failure_summary: state === "failed" ? "Triage dependency was unavailable" : null,
    result:
      state === "succeeded"
        ? {
            incident_summary: "Checkout is slow",
            severity: "HIGH",
            likely_root_cause: "Database connection saturation",
            recommended_actions: ["Inspect pool utilization"],
            escalate: true,
            confidence: 0.86,
            evidence: [],
            timeline: [],
            triage_id: "run-1",
          }
        : null,
    evidence:
      state === "succeeded"
        ? [{ sequence: 0, type: "metric", source: "latency", reason: "p95 increased", origin: "retrieval", score: 0.9 }]
        : [],
    operational_context: null,
  };
}

describe("incident workflow states", () => {
  it("validates required incident input", () => {
    expect(validateIncidentDraft(draft)).toBeNull();
    expect(validateIncidentDraft({ ...draft, title: "" })).toMatch(/title/i);
  });

  it.each(["queued", "running", "cancelled"])("renders %s state", (state) => {
    const html = renderToStaticMarkup(
      React.createElement(RunView, {
        incident: null,
        accepted,
        run: run(state),
      }),
    );
    expect(html).toContain(state);
    expect(html).toContain("run-1");
  });

  it("renders completed result and evidence", () => {
    const html = renderToStaticMarkup(
      React.createElement(RunView, {
        incident: null,
        accepted,
        run: run("succeeded"),
      }),
    );
    expect(html).toContain("Database connection saturation");
    expect(html).toContain("Inspect pool utilization");
    expect(html).toContain("p95 increased");
  });

  it("renders a safe failed result", () => {
    const html = renderToStaticMarkup(
      React.createElement(RunView, {
        incident: null,
        accepted,
        run: run("failed"),
      }),
    );
    expect(html).toContain("Triage failed");
    expect(html).toContain("Triage dependency was unavailable");
  });
});
