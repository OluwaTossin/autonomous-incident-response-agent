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
    [500, "unavailable"],
  ] as const)("maps backend %s to %s", async (status, kind) => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("internal detail", { status })));
    const client = new HostedApiClient("http://api.internal", 1_000);
    await expect(client.bootstrap("secret")).rejects.toMatchObject({
      status,
      kind,
    } satisfies Partial<HostedApiError>);
  });
});
