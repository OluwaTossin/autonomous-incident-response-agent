import "server-only";

import type {
  ActionProposal,
  AwsIntegration,
  AwsIntegrationCreate,
  AwsIntegrationPage,
  AwsIntegrationUpdate,
  AwsTrustInstructions,
  HostedBootstrap,
  Incident,
  IncidentCreate,
  IncidentPage,
  TriageAccepted,
  TriageEvidence,
  TriageResult,
  TriageRun,
  TriageRunPage,
  FeedbackCreate,
  WorkspaceConfigurationUpdate,
  WorkspaceCreate,
  WorkspaceDetail,
  WorkspaceMetadataUpdate,
  WorkspacePage,
  WorkspaceSummary,
} from "./types";

export class HostedApiError extends Error {
  constructor(
    readonly status: number,
    readonly kind: "unauthenticated" | "forbidden" | "validation" | "not_found" | "conflict" | "unavailable" | "unexpected",
    message: string,
  ) {
    super(message);
  }
}

export interface HostedApi {
  bootstrap(accessToken: string): Promise<HostedBootstrap>;
  listWorkspaces(
    accessToken: string,
    organizationId: string,
    cursor?: string,
  ): Promise<WorkspacePage>;
  getWorkspace(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
  ): Promise<WorkspaceDetail>;
  createWorkspace(
    accessToken: string,
    organizationId: string,
    input: WorkspaceCreate,
  ): Promise<WorkspaceDetail>;
  updateWorkspace(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    input: WorkspaceMetadataUpdate,
  ): Promise<WorkspaceDetail>;
  updateWorkspaceConfiguration(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    input: WorkspaceConfigurationUpdate,
  ): Promise<WorkspaceDetail>;
  archiveWorkspace(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    expectedVersion: number,
  ): Promise<WorkspaceSummary>;
  listAwsIntegrations(accessToken: string, organizationId: string, workspaceId: string): Promise<AwsIntegrationPage>;
  getAwsIntegration(accessToken: string, organizationId: string, workspaceId: string, integrationId: string): Promise<AwsIntegration>;
  createAwsIntegration(accessToken: string, organizationId: string, workspaceId: string, input: AwsIntegrationCreate): Promise<AwsIntegration>;
  updateAwsIntegration(accessToken: string, organizationId: string, workspaceId: string, integrationId: string, input: AwsIntegrationUpdate): Promise<AwsIntegration>;
  getAwsTrustInstructions(accessToken: string, organizationId: string, workspaceId: string, integrationId: string): Promise<AwsTrustInstructions>;
  verifyAwsIntegration(accessToken: string, organizationId: string, workspaceId: string, integrationId: string, expectedVersion: number): Promise<AwsIntegration>;
  disableAwsIntegration(accessToken: string, organizationId: string, workspaceId: string, integrationId: string, expectedVersion: number): Promise<AwsIntegration>;
  createIncident(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    input: IncidentCreate,
  ): Promise<Incident>;
  listIncidents(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    query?: string,
  ): Promise<IncidentPage>;
  getIncident(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    incidentId: string,
  ): Promise<Incident>;
  transitionIncident(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    incidentId: string,
    state: "investigating" | "resolved" | "closed",
  ): Promise<Incident>;
  listTriageRuns(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    query?: string,
  ): Promise<TriageRunPage>;
  requestTriage(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    incidentId: string,
    idempotencyKey: string,
  ): Promise<TriageAccepted>;
  getTriageRun(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    triageRunId: string,
  ): Promise<TriageRun>;
  getTriageResult(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    triageRunId: string,
  ): Promise<TriageResult>;
  getTriageEvidence(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    triageRunId: string,
  ): Promise<TriageEvidence[]>;
  listActionProposals(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    triageRunId: string,
  ): Promise<ActionProposal[]>;
  cancelTriage(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    triageRunId: string,
  ): Promise<TriageRun>;
  submitFeedback(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    triageRunId: string,
    input: FeedbackCreate,
  ): Promise<{ feedback_id: string; triage_run_id: string; created_at: string }>;
}

export class HostedApiClient implements HostedApi {
  constructor(
    private readonly baseUrl: string,
    private readonly timeoutMs: number,
  ) {}

  bootstrap(accessToken: string): Promise<HostedBootstrap> {
    return this.request("/v3/me", accessToken);
  }

  listWorkspaces(
    accessToken: string,
    organizationId: string,
    cursor?: string,
  ): Promise<WorkspacePage> {
    const query = new URLSearchParams({ limit: "50" });
    if (cursor) query.set("cursor", cursor);
    return this.request(
      `${this.organizationScope(organizationId, "/workspaces")}?${query}`,
      accessToken,
    );
  }

  getWorkspace(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
  ): Promise<WorkspaceDetail> {
    return this.request(this.workspaceScope(organizationId, workspaceId), accessToken);
  }

  createWorkspace(
    accessToken: string,
    organizationId: string,
    input: WorkspaceCreate,
  ): Promise<WorkspaceDetail> {
    return this.request(this.organizationScope(organizationId, "/workspaces"), accessToken, {
      method: "POST",
      body: JSON.stringify(input),
    });
  }

  updateWorkspace(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    input: WorkspaceMetadataUpdate,
  ): Promise<WorkspaceDetail> {
    return this.request(this.workspaceScope(organizationId, workspaceId), accessToken, {
      method: "PATCH",
      body: JSON.stringify(input),
    });
  }

  updateWorkspaceConfiguration(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    input: WorkspaceConfigurationUpdate,
  ): Promise<WorkspaceDetail> {
    return this.request(
      `${this.workspaceScope(organizationId, workspaceId)}/configuration`,
      accessToken,
      { method: "PATCH", body: JSON.stringify(input) },
    );
  }

  archiveWorkspace(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    expectedVersion: number,
  ): Promise<WorkspaceSummary> {
    return this.request(
      `${this.workspaceScope(organizationId, workspaceId)}/archive`,
      accessToken,
      { method: "POST", body: JSON.stringify({ expected_version: expectedVersion }) },
    );
  }

  listAwsIntegrations(accessToken: string, organizationId: string, workspaceId: string): Promise<AwsIntegrationPage> {
    return this.request(`${this.scope(organizationId, workspaceId, "/integrations/aws")}?limit=100`, accessToken);
  }

  getAwsIntegration(accessToken: string, organizationId: string, workspaceId: string, integrationId: string): Promise<AwsIntegration> {
    return this.request(this.scope(organizationId, workspaceId, `/integrations/aws/${encodeURIComponent(integrationId)}`), accessToken);
  }

  createAwsIntegration(accessToken: string, organizationId: string, workspaceId: string, input: AwsIntegrationCreate): Promise<AwsIntegration> {
    return this.request(this.scope(organizationId, workspaceId, "/integrations/aws"), accessToken, { method: "POST", body: JSON.stringify(input) });
  }

  updateAwsIntegration(accessToken: string, organizationId: string, workspaceId: string, integrationId: string, input: AwsIntegrationUpdate): Promise<AwsIntegration> {
    return this.request(this.scope(organizationId, workspaceId, `/integrations/aws/${encodeURIComponent(integrationId)}`), accessToken, { method: "PATCH", body: JSON.stringify(input) });
  }

  getAwsTrustInstructions(accessToken: string, organizationId: string, workspaceId: string, integrationId: string): Promise<AwsTrustInstructions> {
    return this.request(this.scope(organizationId, workspaceId, `/integrations/aws/${encodeURIComponent(integrationId)}/trust-instructions`), accessToken);
  }

  verifyAwsIntegration(accessToken: string, organizationId: string, workspaceId: string, integrationId: string, expectedVersion: number): Promise<AwsIntegration> {
    return this.request(this.scope(organizationId, workspaceId, `/integrations/aws/${encodeURIComponent(integrationId)}/verify`), accessToken, { method: "POST", body: JSON.stringify({ expected_version: expectedVersion }) });
  }

  disableAwsIntegration(accessToken: string, organizationId: string, workspaceId: string, integrationId: string, expectedVersion: number): Promise<AwsIntegration> {
    return this.request(this.scope(organizationId, workspaceId, `/integrations/aws/${encodeURIComponent(integrationId)}/disable`), accessToken, { method: "POST", body: JSON.stringify({ expected_version: expectedVersion }) });
  }

  createIncident(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    input: IncidentCreate,
  ): Promise<Incident> {
    return this.request(this.scope(organizationId, workspaceId, "/incidents"), accessToken, {
      method: "POST",
      body: JSON.stringify(input),
    });
  }

  listIncidents(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    query = "",
  ): Promise<IncidentPage> {
    return this.request(
      `${this.scope(organizationId, workspaceId, "/incidents")}${query ? `?${query}` : ""}`,
      accessToken,
    );
  }

  getIncident(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    incidentId: string,
  ): Promise<Incident> {
    return this.request(
      this.scope(organizationId, workspaceId, `/incidents/${encodeURIComponent(incidentId)}`),
      accessToken,
    );
  }

  transitionIncident(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    incidentId: string,
    state: "investigating" | "resolved" | "closed",
  ): Promise<Incident> {
    return this.request(
      this.scope(organizationId, workspaceId, `/incidents/${encodeURIComponent(incidentId)}/state`),
      accessToken,
      { method: "PATCH", body: JSON.stringify({ state }) },
    );
  }

  listTriageRuns(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    query = "",
  ): Promise<TriageRunPage> {
    return this.request(
      `${this.scope(organizationId, workspaceId, "/triage-runs")}${query ? `?${query}` : ""}`,
      accessToken,
    );
  }

  requestTriage(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    incidentId: string,
    idempotencyKey: string,
  ): Promise<TriageAccepted> {
    return this.request(
      this.scope(
        organizationId,
        workspaceId,
        `/incidents/${encodeURIComponent(incidentId)}/triage`,
      ),
      accessToken,
      { method: "POST", headers: { "idempotency-key": idempotencyKey } },
    );
  }

  getTriageRun(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    triageRunId: string,
  ): Promise<TriageRun> {
    return this.request(
      this.scope(
        organizationId,
        workspaceId,
        `/triage-runs/${encodeURIComponent(triageRunId)}`,
      ),
      accessToken,
    );
  }

  getTriageResult(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    triageRunId: string,
  ): Promise<TriageResult> {
    return this.request(
      this.scope(
        organizationId,
        workspaceId,
        `/triage-runs/${encodeURIComponent(triageRunId)}/result`,
      ),
      accessToken,
    );
  }

  getTriageEvidence(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    triageRunId: string,
  ): Promise<TriageEvidence[]> {
    return this.request(
      this.scope(
        organizationId,
        workspaceId,
        `/triage-runs/${encodeURIComponent(triageRunId)}/evidence`,
      ),
      accessToken,
    );
  }

  listActionProposals(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    triageRunId: string,
  ): Promise<ActionProposal[]> {
    return this.request(
      this.scope(
        organizationId,
        workspaceId,
        `/triage-runs/${encodeURIComponent(triageRunId)}/action-proposals`,
      ),
      accessToken,
    );
  }

  cancelTriage(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    triageRunId: string,
  ): Promise<TriageRun> {
    return this.request(
      this.scope(
        organizationId,
        workspaceId,
        `/triage-runs/${encodeURIComponent(triageRunId)}/cancel`,
      ),
      accessToken,
      { method: "POST" },
    );
  }

  submitFeedback(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    triageRunId: string,
    input: FeedbackCreate,
  ): Promise<{ feedback_id: string; triage_run_id: string; created_at: string }> {
    return this.request(
      this.scope(
        organizationId,
        workspaceId,
        `/triage-runs/${encodeURIComponent(triageRunId)}/feedback`,
      ),
      accessToken,
      { method: "POST", body: JSON.stringify(input) },
    );
  }

  private scope(organizationId: string, workspaceId: string, suffix: string): string {
    return `/v3/organizations/${encodeURIComponent(
      organizationId,
    )}/workspaces/${encodeURIComponent(workspaceId)}${suffix}`;
  }

  private organizationScope(organizationId: string, suffix: string): string {
    return `/v3/organizations/${encodeURIComponent(organizationId)}${suffix}`;
  }

  private workspaceScope(organizationId: string, workspaceId: string): string {
    return this.organizationScope(
      organizationId,
      `/workspaces/${encodeURIComponent(workspaceId)}`,
    );
  }

  private async request<T>(
    path: string,
    accessToken: string,
    init: RequestInit = {},
  ): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers: {
          accept: "application/json",
          "content-type": "application/json",
          ...init.headers,
          authorization: `Bearer ${accessToken}`,
        },
        cache: "no-store",
        signal: AbortSignal.timeout(this.timeoutMs),
      });
    } catch {
      throw new HostedApiError(503, "unavailable", "AIRA is temporarily unavailable");
    }
    if (!response.ok) {
      throw new HostedApiError(
        response.status,
        statusKind(response.status),
        safeMessage(response.status),
      );
    }
    return (await response.json()) as T;
  }
}

function statusKind(status: number): HostedApiError["kind"] {
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 422 || status === 400) return "validation";
  if (status >= 500) return "unavailable";
  return "unexpected";
}

function safeMessage(status: number): string {
  if (status === 401) return "Your AIRA session is no longer authorized";
  if (status === 403) return "You do not have access to this operation";
  if (status === 404) return "The requested AIRA resource was not found";
  if (status === 409) return "The requested operation conflicts with current state";
  if (status === 400 || status === 422) return "The submitted data was not accepted";
  return status >= 500
    ? "AIRA is temporarily unavailable"
    : "The request could not be completed";
}
