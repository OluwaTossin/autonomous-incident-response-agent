/** Mirrors `EvidenceItem` / `TriageOutput` from the FastAPI backend. */

export type EvidenceType =
  | "log"
  | "incident"
  | "runbook"
  | "knowledge"
  | "decision"
  | "metric"
  | "alert"
  | "other";

export interface EvidenceItem {
  type: EvidenceType;
  source: string;
  reason: string;
}

export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface TriageResponse {
  incident_summary: string;
  service_name?: string | null;
  severity: Severity;
  likely_root_cause: string;
  recommended_actions: string[];
  escalate: boolean;
  confidence: number;
  evidence: EvidenceItem[];
  conflicting_signals_summary?: string | null;
  timeline: string[];
  triage_id: string;
}

export function isTriageResponse(x: unknown): x is TriageResponse {
  if (!x || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  return (
    typeof o.incident_summary === "string" &&
    typeof o.severity === "string" &&
    typeof o.likely_root_cause === "string" &&
    Array.isArray(o.recommended_actions) &&
    typeof o.escalate === "boolean" &&
    typeof o.confidence === "number" &&
    Array.isArray(o.evidence) &&
    Array.isArray(o.timeline) &&
    typeof o.triage_id === "string"
  );
}
