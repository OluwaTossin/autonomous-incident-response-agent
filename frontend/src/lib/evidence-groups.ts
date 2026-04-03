/**
 * Mirrors `app/ui/triage_display.py` `_group_evidence` — same buckets as Gradio.
 */

import type { EvidenceItem } from "./types";

export type EvidenceGroupKey = "logs" | "incidents" | "metrics" | "knowledge";

export const EVIDENCE_SECTIONS: {
  key: EvidenceGroupKey;
  title: string;
  hint: string;
}[] = [
  { key: "logs", title: "Logs", hint: "Log lines and log-derived retrieval" },
  { key: "incidents", title: "Incidents", hint: "Past incidents and narratives" },
  { key: "metrics", title: "Metrics & alerts", hint: "Metrics, SLOs, and alert context" },
  {
    key: "knowledge",
    title: "Runbooks & knowledge",
    hint: "Runbooks, docs, and other sources",
  },
];

export function groupEvidence(items: EvidenceItem[]): Record<EvidenceGroupKey, EvidenceItem[]> {
  const groups: Record<EvidenceGroupKey, EvidenceItem[]> = {
    logs: [],
    incidents: [],
    metrics: [],
    knowledge: [],
  };
  for (const item of items) {
    const t = String(item.type || "other").toLowerCase();
    if (t === "log") groups.logs.push(item);
    else if (t === "incident") groups.incidents.push(item);
    else if (t === "metric" || t === "alert") groups.metrics.push(item);
    else groups.knowledge.push(item);
  }
  return groups;
}
