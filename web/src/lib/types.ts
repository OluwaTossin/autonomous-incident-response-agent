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

export interface AwsCapabilityCheck {
  capability: string;
  region: string;
  passed: boolean;
  error_code: string | null;
  summary: string | null;
}

export interface AwsVerification {
  assume_role_passed: boolean;
  account_identity_passed: boolean;
  succeeded: boolean;
  verified_at: string;
  error_code: string | null;
  summary: string | null;
  checks: AwsCapabilityCheck[];
}

export interface AwsIntegration {
  integration_id: string;
  provider: "aws";
  display_name: string;
  aws_account_id: string;
  role_arn: string | null;
  enabled_regions: string[];
  log_group_names: string[];
  state: "draft" | "pending_verification" | "ready" | "error" | "disabled";
  version: number;
  verification: AwsVerification | null;
  created_at: string;
  updated_at: string;
  disabled_at: string | null;
}

export interface AwsIntegrationPage { items: AwsIntegration[]; }

export interface AwsIntegrationCreate {
  display_name: string;
  aws_account_id: string;
  enabled_regions: string[];
  log_group_names?: string[];
}

export interface AwsIntegrationUpdate {
  expected_version: number;
  display_name?: string;
  aws_account_id?: string;
  role_arn?: string;
  enabled_regions?: string[];
  log_group_names?: string[];
}

export interface AwsTrustInstructions {
  trusted_principal_arn: string;
  external_id: string;
  required_sts_action: "sts:AssumeRole";
  expected_role_arn_format: string;
  trust_policy: Record<string, unknown>;
  permission_policy: Record<string, unknown>;
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

export interface IncidentContext {
  snapshot_id: string;
  integration_id: string;
  provider: string;
  region: string;
  status: "complete" | "partial";
  window_start: string;
  window_end: string;
  collected_at: string;
  policy_version: string;
  truncated: boolean;
  diagnostics: Array<{
    collector: string;
    status: string;
    code: string | null;
    summary: string | null;
  }>;
  items: Array<{
    sequence: number;
    type: "aws_cloudwatch_alarm" | "aws_cloudwatch_metric" | "aws_cloudwatch_log";
    source: string;
    observed_at: string;
    content: Record<string, unknown>;
    truncated: boolean;
  }>;
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
  operational_context: IncidentContext | null;
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

export interface ActionProposal {
  action_proposal_id: string;
  incident_id: string;
  triage_run_id: string;
  proposal_type: "acknowledge_incident" | "manual_investigation" | "restart_workload" | "scale_workload" | "rollback_deployment";
  target: {
    type: "incident" | "service" | "aws_resource";
    identifier: string;
    provider: string;
    provenance: "incident" | "operational_context" | "unknown";
    integration_id: string | null;
    account_id: string | null;
    region: string | null;
  };
  summary: string;
  rationale: string;
  parameters: Record<string, unknown>;
  risk_level: "low" | "medium" | "high" | "critical";
  reversibility: "reversible" | "partially_reversible" | "irreversible" | "unknown";
  policy_status: "allowed_for_review" | "blocked" | "manual_only";
  policy_reason: string;
  lifecycle_state: "ready_for_review" | "blocked" | "manual_only" | "superseded" | "cancelled";
  source_result_version: number;
  source_result_hash: string;
  proposal_schema_version: number;
  created_by_type: "human" | "service_account" | "system";
  created_at: string;
}

export interface Approval {
  approval_id: string;
  action_proposal_id: string;
  state: "requested" | "approved" | "rejected" | "expired" | "cancelled";
  state_version: number;
  proposal_schema_version: number;
  source_result_version: number;
  source_result_hash: string;
  normalized_action_hash: string;
  requested_by_type: "human";
  requested_by_id: string;
  requested_at: string;
  expires_at: string;
  decided_by_type: "human" | null;
  decided_by_id: string | null;
  decided_at: string | null;
  decision_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface ExecutionIntent {
  execution_intent_id: string;
  action_proposal_id: string;
  approval_id: string;
  incident_id: string;
  triage_run_id: string;
  lifecycle_state: "prepared" | "invalidated" | "cancelled";
  connector_kind: "internal";
  operation_kind: "acknowledge_incident";
  provider: "aira";
  target: ActionProposal["target"];
  parameters: Record<string, unknown>;
  request_schema_version: number;
  proposal_schema_version: number;
  source_result_version: number;
  source_result_hash: string;
  normalized_action_hash: string;
  approval_state_version: number;
  approval_binding_hash: string;
  intent_hash: string;
  risk_level: ActionProposal["risk_level"];
  reversibility: ActionProposal["reversibility"];
  policy_version: number;
  approved_by_type: "human";
  approved_by_id: string;
  approved_at: string;
  created_by_type: "human" | "service_account" | "system";
  created_at: string;
  updated_at: string;
  execute_before: string;
  terminal_at: string | null;
  terminal_reason: string | null;
  validation_status: "passed";
  execution_status: "not_executed";
}

export interface FeedbackCreate {
  diagnosis_correct: boolean | null;
  actions_useful: boolean | null;
  notes: string | null;
}

export interface QuotaSummary {
  quota_type: string;
  status: "allowed" | "warning" | "rejected";
  current: number;
  limit: number;
  remaining: number;
  reset_at: string | null;
  policy_version: number;
}

export interface UsageSummary {
  organization_id: string;
  workspace_id: string;
  generated_at: string;
  quotas: QuotaSummary[];
  billing_enabled: false;
}

export type BrowserErrorCode =
  | "unauthenticated"
  | "forbidden"
  | "validation"
  | "unavailable"
  | "not_found"
  | "conflict"
  | "quota_exceeded"
  | "unexpected";

export interface BrowserError {
  error: { code: BrowserErrorCode; message: string };
}
