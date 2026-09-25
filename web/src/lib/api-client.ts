import "server-only";

import type {
  HostedBootstrap,
  Incident,
  IncidentCreate,
  TriageAccepted,
  TriageEvidence,
  TriageResult,
  TriageRun,
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
  createIncident(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    input: IncidentCreate,
  ): Promise<Incident>;
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
  cancelTriage(
    accessToken: string,
    organizationId: string,
    workspaceId: string,
    triageRunId: string,
  ): Promise<TriageRun>;
}

export class HostedApiClient implements HostedApi {
  constructor(
    private readonly baseUrl: string,
    private readonly timeoutMs: number,
  ) {}

  bootstrap(accessToken: string): Promise<HostedBootstrap> {
    return this.request("/v3/me", accessToken);
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

  private scope(organizationId: string, workspaceId: string, suffix: string): string {
    return `/v3/organizations/${encodeURIComponent(
      organizationId,
    )}/workspaces/${encodeURIComponent(workspaceId)}${suffix}`;
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
