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
  membership_state: "active";
  permissions: string[];
  workspaces: BootstrapWorkspace[];
}

export interface HostedBootstrap {
  user_id: string;
  organizations: BootstrapOrganization[];
}

export interface WorkspaceSummary {
  workspace_id: string;
  organization_id: string;
  name: string;
  slug: string;
  description: string | null;
  state: "active" | "archived";
  version: number;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceConfiguration {
  schema_version: number;
  version: number;
  rag_top_k: number;
  llm_temperature: number;
  updated_at: string;
}

export interface WorkspaceDetail {
  workspace: WorkspaceSummary;
  configuration: WorkspaceConfiguration;
}

export interface WorkspacePage {
  items: WorkspaceSummary[];
  next_cursor: string | null;
}

export interface WorkspaceCreate {
  name: string;
  slug: string;
  description?: string | null;
}

export interface WorkspaceMetadataUpdate {
  expected_version: number;
  name?: string;
  slug?: string;
  description?: string | null;
}

export interface WorkspaceConfigurationUpdate {
  expected_version: number;
  rag_top_k?: number;
  llm_temperature?: number;
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
  external_event_id: string | null;
  source_url: string | null;
  description: string;
  metric_summary: string;
  severity_hint: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL" | null;
  observed_at: string;
  created_at: string;
  updated_at: string;
}

export interface IncidentSummary extends Incident {
  latest_triage_run_id: string | null;
  latest_triage_state: string | null;
  latest_severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL" | null;
  latest_confidence: number | null;
  latest_escalate: boolean | null;
  triage_run_count: number;
}

export interface IncidentPage {
  items: IncidentSummary[];
  next_cursor: string | null;
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
  document_id?: string | null;
  document_version_id?: string | null;
  knowledge_index_version_id?: string | null;
  chunk_index?: number | null;
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
  conflicting_signals_summary?: string | null;
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
  attempt_count?: number;
  max_attempts?: number;
  next_attempt_at?: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  failure_code: string | null;
  failure_category: string | null;
  failure_summary: string | null;
  result: TriageResult | null;
  evidence: TriageEvidence[];
}

export interface TriageRunSummary {
  triage_run_id: string;
  triage_id: string;
  incident_id: string;
  state: string;
  job_state: string;
  attempt_count: number;
  max_attempts: number;
  next_attempt_at: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  failure_category: string | null;
  failure_summary: string | null;
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL" | null;
  confidence: number | null;
  escalate: boolean | null;
}

export interface TriageRunPage {
  items: TriageRunSummary[];
  next_cursor: string | null;
}

export interface FeedbackCreate {
  diagnosis_correct: boolean | null;
  actions_useful: boolean | null;
  notes: string | null;
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
