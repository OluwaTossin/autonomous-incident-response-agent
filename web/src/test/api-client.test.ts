import { afterEach, describe, expect, it, vi } from "vitest";
import { HostedApiClient, HostedApiError } from "@/lib/api-client";

afterEach(() => vi.unstubAllGlobals());

describe("hosted server API client", () => {
  it("forwards bearer credentials server-side without returning them", async () => {
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      expect(new Headers(init.headers).get("authorization")).toBe("Bearer access-secret");
      return Response.json({ user_id: "user-1", organizations: [] });
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new HostedApiClient("http://api.internal", 1_000);

    const response = await client.bootstrap("access-secret");

    expect(JSON.stringify(response)).not.toContain("access-secret");
    expect(response.user_id).toBe("user-1");
  });

  it.each([
    [401, "unauthenticated"],
    [403, "forbidden"],
    [422, "validation"],
    [404, "not_found"],
    [409, "conflict"],
    [500, "unavailable"],
  ] as const)("maps backend %s to %s", async (status, kind) => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("internal detail", { status })));
    const client = new HostedApiClient("http://api.internal", 1_000);
    await expect(client.bootstrap("secret")).rejects.toMatchObject({
      status,
      kind,
    } satisfies Partial<HostedApiError>);
  });

  it("uses tenant-scoped workspace routes for management operations", async () => {
    const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
      return Response.json({ url, method: init.method || "GET" });
    });
    vi.stubGlobal("fetch", fetchMock);
    const client = new HostedApiClient("http://api.internal", 1_000);

    await client.listWorkspaces("token", "org one");
    await client.getWorkspace("token", "org one", "workspace one");
    await client.createWorkspace("token", "org one", { name: "Ops", slug: "ops" });
    await client.updateWorkspace("token", "org one", "workspace one", { expected_version: 2, name: "Operations" });
    await client.updateWorkspaceConfiguration("token", "org one", "workspace one", { expected_version: 3, rag_top_k: 12 });
    await client.archiveWorkspace("token", "org one", "workspace one", 2);
    await client.listIncidents("token", "org one", "workspace one", "state=open");
    await client.getIncident("token", "org one", "workspace one", "incident one");
    await client.transitionIncident("token", "org one", "workspace one", "incident one", "investigating");
    await client.listTriageRuns("token", "org one", "workspace one", "incident_id=incident%20one");
    await client.submitFeedback("token", "org one", "workspace one", "run one", { diagnosis_correct: true, actions_useful: null, notes: null });
    await client.listApprovals("token", "org one", "workspace one", "proposal one");
    await client.getApproval("token", "org one", "workspace one", "approval one");
    await client.requestApproval("token", "org one", "workspace one", "proposal one");
    await client.approveApproval("token", "org one", "workspace one", "approval one", "Reviewed");
    await client.rejectApproval("token", "org one", "workspace one", "approval one", "Changed");
    await client.cancelApproval("token", "org one", "workspace one", "approval one", null);

    const calls = fetchMock.mock.calls.map(([url, init]) => [url, init.method || "GET"]);
    expect(calls).toEqual([
      ["http://api.internal/v3/organizations/org%20one/workspaces?limit=50", "GET"],
      ["http://api.internal/v3/organizations/org%20one/workspaces/workspace%20one", "GET"],
      ["http://api.internal/v3/organizations/org%20one/workspaces", "POST"],
      ["http://api.internal/v3/organizations/org%20one/workspaces/workspace%20one", "PATCH"],
      ["http://api.internal/v3/organizations/org%20one/workspaces/workspace%20one/configuration", "PATCH"],
      ["http://api.internal/v3/organizations/org%20one/workspaces/workspace%20one/archive", "POST"],
      ["http://api.internal/v3/organizations/org%20one/workspaces/workspace%20one/incidents?state=open", "GET"],
      ["http://api.internal/v3/organizations/org%20one/workspaces/workspace%20one/incidents/incident%20one", "GET"],
      ["http://api.internal/v3/organizations/org%20one/workspaces/workspace%20one/incidents/incident%20one/state", "PATCH"],
      ["http://api.internal/v3/organizations/org%20one/workspaces/workspace%20one/triage-runs?incident_id=incident%20one", "GET"],
      ["http://api.internal/v3/organizations/org%20one/workspaces/workspace%20one/triage-runs/run%20one/feedback", "POST"],
      ["http://api.internal/v3/organizations/org%20one/workspaces/workspace%20one/action-proposals/proposal%20one/approvals", "GET"],
      ["http://api.internal/v3/organizations/org%20one/workspaces/workspace%20one/approvals/approval%20one", "GET"],
      ["http://api.internal/v3/organizations/org%20one/workspaces/workspace%20one/action-proposals/proposal%20one/approval", "POST"],
      ["http://api.internal/v3/organizations/org%20one/workspaces/workspace%20one/approvals/approval%20one/approve", "POST"],
      ["http://api.internal/v3/organizations/org%20one/workspaces/workspace%20one/approvals/approval%20one/reject", "POST"],
      ["http://api.internal/v3/organizations/org%20one/workspaces/workspace%20one/approvals/approval%20one/cancel", "POST"],
    ]);
  });

  it("uses tenant-scoped AWS integration routes", async () => {
    const fetchMock = vi.fn(async (url: string, init: RequestInit) => Response.json({ url, method: init.method || "GET" }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new HostedApiClient("http://api.internal", 1_000);
    await client.listAwsIntegrations("token", "org", "workspace");
    await client.getAwsIntegration("token", "org", "workspace", "integration");
    await client.createAwsIntegration("token", "org", "workspace", { display_name: "Production", aws_account_id: "123456789012", enabled_regions: ["eu-west-2"] });
    await client.updateAwsIntegration("token", "org", "workspace", "integration", { expected_version: 1, role_arn: "arn:aws:iam::123456789012:role/aira" });
    await client.getAwsTrustInstructions("token", "org", "workspace", "integration");
    await client.verifyAwsIntegration("token", "org", "workspace", "integration", 2);
    await client.disableAwsIntegration("token", "org", "workspace", "integration", 3);
    expect(fetchMock.mock.calls.map(([url, init]) => [url, init.method || "GET"])).toEqual([
      ["http://api.internal/v3/organizations/org/workspaces/workspace/integrations/aws?limit=100", "GET"],
      ["http://api.internal/v3/organizations/org/workspaces/workspace/integrations/aws/integration", "GET"],
      ["http://api.internal/v3/organizations/org/workspaces/workspace/integrations/aws", "POST"],
      ["http://api.internal/v3/organizations/org/workspaces/workspace/integrations/aws/integration", "PATCH"],
      ["http://api.internal/v3/organizations/org/workspaces/workspace/integrations/aws/integration/trust-instructions", "GET"],
      ["http://api.internal/v3/organizations/org/workspaces/workspace/integrations/aws/integration/verify", "POST"],
      ["http://api.internal/v3/organizations/org/workspaces/workspace/integrations/aws/integration/disable", "POST"],
    ]);
  });
});
