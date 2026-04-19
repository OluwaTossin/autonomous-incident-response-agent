"use client";

import dynamic from "next/dynamic";
import { useCallback, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { ConfidenceBar } from "@/components/confidence-bar";
import { EvidenceGrouped } from "@/components/evidence-grouped";
import { OperationalActionsList } from "@/components/operational-actions";
import { Spinner } from "@/components/spinner";
import { TriageIdBlock } from "@/components/triage-id-block";
import { SAMPLE_INCIDENTS } from "@/data/sample-incidents";
import { ApiFailure } from "@/lib/api-errors";
import { postTriage, postTriageFeedback } from "@/lib/api";
import { publicApiBase } from "@/lib/config";
import type { Severity, TriageResponse } from "@/lib/types";

const MonacoIncidentEditor = dynamic(
  () =>
    import("@/components/monaco-incident-editor").then((m) => m.MonacoIncidentEditor),
  {
    ssr: false,
    loading: () => (
      <div className="h-[min(40vh,360px)] animate-pulse rounded-lg bg-zinc-200 dark:bg-zinc-800" />
    ),
  },
);

function severityStyles(s: Severity): string {
  switch (s) {
    case "LOW":
      return "bg-emerald-500/15 text-emerald-700 ring-emerald-500/40 dark:text-emerald-300";
    case "MEDIUM":
      return "bg-amber-500/15 text-amber-800 ring-amber-500/40 dark:text-amber-200";
    case "HIGH":
      return "bg-orange-500/15 text-orange-800 ring-orange-500/40 dark:text-orange-200";
    case "CRITICAL":
      return "bg-red-500/20 text-red-800 ring-red-500/50 dark:text-red-200";
    default:
      return "bg-zinc-500/15 text-zinc-700 ring-zinc-500/30";
  }
}

function TimelineVisual({ events }: { events: string[] }) {
  if (!events.length) {
    return (
      <p className="text-sm text-zinc-500 dark:text-zinc-400">No timeline extracted.</p>
    );
  }
  return (
    <ol className="relative ms-2 border-s border-zinc-300 dark:border-zinc-600 ps-6">
      {events.map((line, i) => (
        <li key={i} className="mb-4 last:mb-0">
          <span className="absolute -start-[5px] mt-1.5 h-2.5 w-2.5 rounded-full bg-violet-500 ring-4 ring-white dark:ring-zinc-950" />
          <p className="text-sm leading-relaxed text-zinc-800 dark:text-zinc-200">{line}</p>
        </li>
      ))}
    </ol>
  );
}

function formatApiError(e: unknown): string {
  if (e instanceof ApiFailure) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

export function TriageConsole() {
  const apiBase = useMemo(() => publicApiBase(), []);
  const defaultJson = useMemo(
    () => JSON.stringify(SAMPLE_INCIDENTS[0].payload, null, 2),
    [],
  );
  const [editorJson, setEditorJson] = useState(defaultJson);
  const [sampleId, setSampleId] = useState(SAMPLE_INCIDENTS[0].id);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<TriageResponse | null>(null);
  const [triageError, setTriageError] = useState<string | null>(null);
  const [triageErrorRetryable, setTriageErrorRetryable] = useState(false);
  const [diagYes, setDiagYes] = useState<boolean | null>(null);
  const [actionsYes, setActionsYes] = useState<boolean | null>(null);
  const [notes, setNotes] = useState("");
  const [feedbackBusy, setFeedbackBusy] = useState(false);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const lastIncidentBodyRef = useRef<Record<string, unknown> | null>(null);

  const onSampleChange = useCallback((id: string) => {
    setSampleId(id);
    const s = SAMPLE_INCIDENTS.find((x) => x.id === id);
    if (s) setEditorJson(JSON.stringify(s.payload, null, 2));
  }, []);

  const runTriage = useCallback(
    async (opts?: { incident?: Record<string, unknown> }) => {
      let body: Record<string, unknown>;
      try {
        if (opts?.incident) {
          body = opts.incident;
        } else {
          const parsed = JSON.parse(editorJson) as unknown;
          if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
            throw new Error("Incident must be a JSON object");
          }
          body = parsed as Record<string, unknown>;
        }
      } catch (e) {
        toast.error("Invalid JSON", {
          description: e instanceof Error ? e.message : "Parse error",
        });
        return;
      }

      lastIncidentBodyRef.current = body;
      setTriageError(null);
      setTriageErrorRetryable(false);
      setLoading(true);
      setResult(null);
      setDiagYes(null);
      setActionsYes(null);
      setNotes("");
      try {
        const out = await postTriage(apiBase, body);
        setResult(out);
        toast.success("Triage complete", { description: out.triage_id });
      } catch (e) {
        const af = e instanceof ApiFailure ? e : null;
        setTriageError(formatApiError(e));
        setTriageErrorRetryable(af?.isRetryable ?? true);
      } finally {
        setLoading(false);
      }
    },
    [apiBase, editorJson],
  );

  const retryTriage = useCallback(() => {
    const b = lastIncidentBodyRef.current;
    if (b) void runTriage({ incident: b });
  }, [runTriage]);

  const submitFeedback = useCallback(async () => {
    if (!result?.triage_id) {
      toast.warning("Run triage first");
      return;
    }
    if (diagYes === null || actionsYes === null) {
      toast.warning("Select Yes or No for both questions");
      return;
    }
    setFeedbackBusy(true);
    setFeedbackError(null);
    try {
      await postTriageFeedback(apiBase, {
        triage_id: result.triage_id,
        diagnosis_correct: diagYes,
        actions_useful: actionsYes,
        notes: notes.trim(),
      });
      toast.success("Feedback recorded", {
        description: "Linked via triage_id to server JSONL / Phase 6 loop",
      });
    } catch (e) {
      setFeedbackError(formatApiError(e));
    } finally {
      setFeedbackBusy(false);
    }
  }, [apiBase, result, diagYes, actionsYes, notes]);

  const retryFeedback = useCallback(() => {
    void submitFeedback();
  }, [submitFeedback]);

  return (
    <div className="mx-auto max-w-7xl space-y-6 px-4 py-8">
      <header className="space-y-2 border-b border-zinc-200 pb-6 dark:border-zinc-800">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Triage</h1>
        <p className="max-w-3xl text-sm text-zinc-600 dark:text-zinc-400">
          <span className="text-zinc-500">API base ·</span>{" "}
          <span className="break-all font-mono text-violet-600 dark:text-violet-400">{apiBase}</span>
          <span className="text-zinc-500"> · </span>
          <code className="rounded bg-zinc-100 px-1 text-xs dark:bg-zinc-800">POST /triage</code>
          <span className="text-zinc-500"> · </span>
          <code className="rounded bg-zinc-100 px-1 text-xs dark:bg-zinc-800">POST /n8n/triage-feedback</code>
        </p>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Evidence is grouped by source; timeline and feedback follow the same contracts as the API
          and optional Gradio debug UI.
        </p>
      </header>

      {triageError ? (
        <div
          role="alert"
          className="flex flex-col gap-3 rounded-xl border border-red-200 bg-red-50 p-4 dark:border-red-900 dark:bg-red-950/40"
        >
          <div>
            <p className="text-sm font-semibold text-red-900 dark:text-red-100">Triage request failed</p>
            <p className="mt-1 text-sm text-red-800 dark:text-red-200">{triageError}</p>
            <p className="mt-2 text-xs text-red-700/90 dark:text-red-300/90">
              Check API health, CORS, and that the URL matches your deployed stack. Validation errors
              usually mean the incident JSON does not match the API schema.
            </p>
          </div>
          {triageErrorRetryable ? (
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={retryTriage}
                disabled={loading}
                className="rounded-lg bg-red-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-800 disabled:opacity-50 dark:bg-red-200 dark:text-red-950 dark:hover:bg-white"
              >
                Retry last request
              </button>
              <button
                type="button"
                onClick={() => {
                  setTriageError(null);
                  setTriageErrorRetryable(false);
                }}
                className="rounded-lg border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-900 hover:bg-red-50 dark:border-red-800 dark:bg-red-950 dark:text-red-100 dark:hover:bg-red-900"
              >
                Dismiss
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setTriageError(null)}
              className="self-start rounded-lg border border-red-300 bg-white px-3 py-1.5 text-sm font-medium text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100"
            >
              Dismiss
            </button>
          )}
        </div>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="relative">
          {loading ? (
            <div
              className="absolute inset-0 z-10 flex flex-col items-center justify-center rounded-xl border border-zinc-200 bg-white/90 px-6 text-center backdrop-blur-sm dark:border-zinc-800 dark:bg-zinc-950/90"
              aria-live="polite"
              aria-busy="true"
            >
              <Spinner />
              <p className="mt-4 text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                Analyzing incident…
              </p>
              <p className="mt-1 max-w-xs text-xs text-zinc-600 dark:text-zinc-400">
                Retrieving knowledge (RAG) and running the triage model — this can take up to a few
                minutes on cold starts.
              </p>
            </div>
          ) : null}
          <section className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
              1 · Incident input
            </h2>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <label className="text-sm text-zinc-600 dark:text-zinc-400">Sample</label>
              <select
                value={sampleId}
                disabled={loading}
                onChange={(e) => onSampleChange(e.target.value)}
                className="rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-900"
              >
                {SAMPLE_INCIDENTS.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
            <MonacoIncidentEditor
              value={editorJson}
              onChange={setEditorJson}
              readOnly={loading}
            />
            <button
              type="button"
              onClick={() => void runTriage()}
              disabled={loading}
              className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg bg-violet-600 px-4 py-2.5 text-sm font-medium text-white shadow hover:bg-violet-500 disabled:opacity-50"
            >
              {loading ? (
                <>
                  <Spinner className="h-4 w-4 text-white" />
                  Running triage…
                </>
              ) : (
                "Run triage"
              )}
            </button>
          </section>
        </div>

        <section className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
            2 · Triage output
          </h2>
          {!result ? (
            <p className="text-sm text-zinc-500">
              {loading
                ? "Output will appear when the request completes."
                : "Run triage to see structured output."}
            </p>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-[13px]">
                <span
                  className={`inline-flex rounded-full px-3.5 py-1 text-xs font-bold uppercase tracking-wide ring-1 ${severityStyles(result.severity)}`}
                >
                  {result.severity}
                </span>
                <span className="text-zinc-500 dark:text-zinc-400">
                  Service ·{" "}
                  <strong className="text-zinc-900 dark:text-zinc-100">
                    {result.service_name?.trim() || "—"}
                  </strong>
                </span>
                <span className="text-zinc-500 dark:text-zinc-400">
                  Escalate ·{" "}
                  <strong
                    className={
                      result.escalate
                        ? "text-amber-800 dark:text-amber-300"
                        : "text-zinc-700 dark:text-zinc-300"
                    }
                  >
                    {result.escalate ? "yes" : "no"}
                  </strong>
                </span>
              </div>
              <ConfidenceBar confidence={result.confidence} />
              <TriageIdBlock triageId={result.triage_id} />
              <div>
                <h3 className="text-xs font-medium uppercase text-zinc-500">Summary</h3>
                <p className="mt-1 text-sm text-zinc-800 dark:text-zinc-200">
                  {result.incident_summary}
                </p>
              </div>
              <div>
                <h3 className="text-xs font-medium uppercase text-zinc-500">Root cause</h3>
                <p className="mt-1 text-sm text-zinc-800 dark:text-zinc-200">
                  {result.likely_root_cause}
                </p>
              </div>
              {result.conflicting_signals_summary ? (
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
                  <span className="font-medium">Conflicting signals · </span>
                  {result.conflicting_signals_summary}
                </div>
              ) : null}
              <div>
                <h3 className="text-xs font-medium uppercase text-zinc-500">
                  Recommended actions
                </h3>
                <p className="mb-1 text-[11px] text-zinc-500 dark:text-zinc-400">
                  Shell-style lines render as commands; URLs and RB-* runbook ids become links when
                  configured.
                </p>
                <OperationalActionsList actions={result.recommended_actions} />
              </div>
            </div>
          )}
        </section>
      </div>

      <section className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
        <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-zinc-500">
          3 · Evidence
        </h2>
        <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
          Grouped like Gradio — expand snippets or open full context for raw signal review.
        </p>
        {result ? (
          <EvidenceGrouped items={result.evidence} />
        ) : (
          <p className="text-sm text-zinc-500">Evidence appears after triage.</p>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
            4 · Timeline
          </h2>
          {result ? (
            <TimelineVisual events={result.timeline} />
          ) : (
            <p className="text-sm text-zinc-500">Timeline appears after triage.</p>
          )}
        </section>

        <section className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
            5 · Feedback (Phase 6 loop)
          </h2>
          <p className="mb-4 text-sm text-zinc-600 dark:text-zinc-400">
            Was this triage useful? Responses are appended server-side (same contract as Gradio /
            n8n).
          </p>
          {feedbackError ? (
            <div
              role="alert"
              className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900 dark:border-red-900 dark:bg-red-950/40 dark:text-red-100"
            >
              <p>{feedbackError}</p>
              <button
                type="button"
                onClick={retryFeedback}
                disabled={feedbackBusy || !result}
                className="mt-2 text-xs font-semibold text-red-800 underline dark:text-red-200"
              >
                Retry feedback
              </button>
            </div>
          ) : null}
          <div className="space-y-4">
            <div>
              <p className="mb-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
                Diagnosis correct?
              </p>
              <div className="flex gap-2">
                {(["yes", "no"] as const).map((v) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => setDiagYes(v === "yes")}
                    disabled={feedbackBusy}
                    className={`rounded-lg px-4 py-2 text-sm font-medium ring-1 transition disabled:opacity-50 ${
                      (v === "yes" && diagYes === true) || (v === "no" && diagYes === false)
                        ? "bg-violet-600 text-white ring-violet-600"
                        : "bg-zinc-100 text-zinc-700 ring-zinc-200 hover:bg-zinc-200 dark:bg-zinc-900 dark:text-zinc-200 dark:ring-zinc-700"
                    }`}
                  >
                    {v === "yes" ? "Yes" : "No"}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <p className="mb-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
                Actions useful?
              </p>
              <div className="flex gap-2">
                {(["yes", "no"] as const).map((v) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => setActionsYes(v === "yes")}
                    disabled={feedbackBusy}
                    className={`rounded-lg px-4 py-2 text-sm font-medium ring-1 transition disabled:opacity-50 ${
                      (v === "yes" && actionsYes === true) || (v === "no" && actionsYes === false)
                        ? "bg-violet-600 text-white ring-violet-600"
                        : "bg-zinc-100 text-zinc-700 ring-zinc-200 hover:bg-zinc-200 dark:bg-zinc-900 dark:text-zinc-200 dark:ring-zinc-700"
                    }`}
                  >
                    {v === "yes" ? "Yes" : "No"}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                Notes
              </label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                disabled={feedbackBusy}
                rows={3}
                className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm disabled:opacity-50 dark:border-zinc-600 dark:bg-zinc-900"
                placeholder="Optional context for reviewers…"
              />
            </div>
            <button
              type="button"
              onClick={() => void submitFeedback()}
              disabled={feedbackBusy || !result}
              className="flex items-center justify-center gap-2 rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
            >
              {feedbackBusy ? (
                <>
                  <Spinner className="h-4 w-4" />
                  Submitting…
                </>
              ) : (
                "Submit feedback"
              )}
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
