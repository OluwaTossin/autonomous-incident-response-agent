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

    const calls = fetchMock.mock.calls.map(([url, init]) => [url, init.method || "GET"]);
    expect(calls).toEqual([
      ["http://api.internal/v3/organizations/org%20one/workspaces?limit=50", "GET"],
      ["http://api.internal/v3/organizations/org%20one/workspaces/workspace%20one", "GET"],
      ["http://api.internal/v3/organizations/org%20one/workspaces", "POST"],
      ["http://api.internal/v3/organizations/org%20one/workspaces/workspace%20one", "PATCH"],
      ["http://api.internal/v3/organizations/org%20one/workspaces/workspace%20one/configuration", "PATCH"],
      ["http://api.internal/v3/organizations/org%20one/workspaces/workspace%20one/archive", "POST"],
    ]);
  });
});
