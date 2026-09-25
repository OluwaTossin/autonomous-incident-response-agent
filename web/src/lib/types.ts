export interface BootstrapWorkspace {
  workspace_id: string;
  name: string;
  slug: string;
}

export interface BootstrapOrganization {
  organization_id: string;
  name: string;
  slug: string;
  role: "owner" | "admin" | "operator" | "viewer";
  permissions: string[];
  workspaces: BootstrapWorkspace[];
}

export interface HostedBootstrap {
  user_id: string;
  organizations: BootstrapOrganization[];
}

export interface IncidentCreate {
  title: string;
  description: string;
  service_name: string;
  environment: string;
  source_provider: string;
  source_type: string;
  observed_at: string;
  severity_hint?: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  metric_summary?: string;
}

export interface Incident {
  incident_id: string;
  workspace_id: string;
  state: string;
  title: string;
  service_name: string;
  environment: string;
  source_provider: string;
  source_type: string;
  observed_at: string;
  created_at: string;
  updated_at: string;
}

export interface TriageAccepted {
  triage_run_id: string;
  triage_id: string;
  incident_id: string;
  job_id: string;
  state: string;
  job_state: string;
  created_at: string;
}

export interface TriageEvidence {
  sequence: number;
  type: string;
  source: string;
  reason: string;
  origin: string | null;
  score: number | null;
}

export interface TriageResult {
  incident_summary: string;
  service_name?: string | null;
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  likely_root_cause: string;
  recommended_actions: string[];
  escalate: boolean;
  confidence: number;
  evidence: Array<{ type: string; source: string; reason: string }>;
  timeline: string[];
  triage_id: string;
}

export interface TriageRun {
  triage_run_id: string;
  triage_id: string;
  incident_id: string;
  job_id: string;
  state: string;
  job_state: string;
  cancellation_requested: boolean;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  failure_code: string | null;
  failure_category: string | null;
  failure_summary: string | null;
  result: TriageResult | null;
  evidence: TriageEvidence[];
}

export type BrowserErrorCode =
  | "unauthenticated"
  | "forbidden"
  | "validation"
  | "unavailable"
  | "not_found"
  | "conflict"
  | "unexpected";

export interface BrowserError {
  error: { code: BrowserErrorCode; message: string };
}
