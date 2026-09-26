import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HostedApiError } from "@/lib/api-client";
import type { BrowserSession } from "@/lib/session-service";

const mocks = vi.hoisted(() => ({
  load: vi.fn(),
  revoke: vi.fn(),
}));

vi.mock("@/lib/config", () => ({
  webConfig: () => ({
    appOrigin: "https://aira.example",
    sessionCookie: "aira_session",
    absoluteSeconds: 3_600,
    secureCookies: true,
  }),
}));
vi.mock("@/lib/runtime", () => ({
  runtime: () => ({ sessions: { load: mocks.load, revoke: mocks.revoke } }),
}));

import { withBffSession } from "@/lib/bff";

const session = {
  accessToken: "server-held-token",
  csrfToken: "csrf",
  displayName: "Operator",
  email: "operator@example.com",
} as BrowserSession;

function request(withCookie = true): NextRequest {
  return new NextRequest("https://aira.example/api/incidents", {
    headers: withCookie ? { cookie: "aira_session=opaque-id" } : {},
  });
}

beforeEach(() => {
  mocks.load.mockReset().mockResolvedValue(session);
  mocks.revoke.mockReset().mockResolvedValue(undefined);
});

describe("BFF authentication and error mapping", () => {
  it("rejects an unauthenticated request", async () => {
    const response = await withBffSession(request(false), false, vi.fn());
    expect(response.status).toBe(401);
  });

  it("passes the server-held credential only to the server operation", async () => {
    const response = await withBffSession(request(), false, async (current) => ({
      user_id: "user-1",
      used: current.accessToken === "server-held-token",
    }));
    expect(response.status).toBe(200);
    const body = await response.text();
    expect(body).toContain('"used":true');
    expect(body).not.toContain("server-held-token");
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(response.headers.get("x-correlation-id")).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("preserves a valid correlation id across the BFF boundary", async () => {
    const id = crypto.randomUUID();
    const correlated = new NextRequest("https://aira.example/api/incidents", {
      headers: { cookie: "aira_session=opaque-id", "x-correlation-id": id },
    });
    const response = await withBffSession(correlated, false, async () => ({ ok: true }));
    expect(response.headers.get("x-correlation-id")).toBe(id);
  });

  it("revokes the local session after a backend 401", async () => {
    const response = await withBffSession(request(), false, async () => {
      throw new HostedApiError(401, "unauthenticated", "Session is no longer authorized");
    });
    expect(response.status).toBe(401);
    expect(mocks.revoke).toHaveBeenCalledWith("opaque-id");
    expect(response.headers.get("set-cookie")).not.toContain("server-held-token");
  });

  it.each([
    [403, "forbidden"],
    [409, "conflict"],
    [422, "validation"],
    [500, "unavailable"],
  ] as const)("keeps backend %s as safe %s response", async (status, kind) => {
    const response = await withBffSession(request(), false, async () => {
      throw new HostedApiError(status, kind, "Safe browser message");
    });
    expect(response.status).toBe(status);
    expect(await response.json()).toEqual({
      error: { code: kind, message: "Safe browser message" },
    });
    expect(mocks.revoke).not.toHaveBeenCalled();
  });
});
