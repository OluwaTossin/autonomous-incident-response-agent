import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { BrowserSession } from "@/lib/session-service";

const mocks = vi.hoisted(() => ({
  prepare: vi.fn(),
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
  runtime: () => ({
    api: { prepareExecutionIntent: mocks.prepare },
    sessions: { load: mocks.load, revoke: mocks.revoke },
  }),
}));

import { POST } from "@/app/api/approvals/[approvalId]/execution-intent/route";

const session = {
  accessToken: "server-held-token",
  csrfToken: "csrf-value",
} as BrowserSession;

function request(csrf = "csrf-value") {
  return new NextRequest("https://aira.example/api/approvals/approval-1/execution-intent", {
    method: "POST",
    headers: {
      cookie: "aira_session=opaque-id",
      "content-type": "application/json",
      origin: "https://aira.example",
      "x-csrf-token": csrf,
    },
    body: JSON.stringify({
      organization_id: "org-1",
      workspace_id: "workspace-1",
    }),
  });
}

beforeEach(() => {
  mocks.prepare.mockReset().mockResolvedValue({ lifecycle_state: "prepared" });
  mocks.load.mockReset().mockResolvedValue(session);
  mocks.revoke.mockReset().mockResolvedValue(undefined);
});

describe("execution-intent mutation BFF", () => {
  it("rejects a stale CSRF token before preparing anything", async () => {
    const response = await POST(request("stale"), {
      params: Promise.resolve({ approvalId: "approval-1" }),
    });
    expect(response.status).toBe(403);
    expect(mocks.prepare).not.toHaveBeenCalled();
  });

  it("forwards only scope and the approved identifier through the server session", async () => {
    const response = await POST(request(), {
      params: Promise.resolve({ approvalId: "approval-1" }),
    });
    expect(response.status).toBe(200);
    expect(mocks.prepare).toHaveBeenCalledWith(
      "server-held-token",
      "org-1",
      "workspace-1",
      "approval-1",
    );
    expect(await response.text()).not.toContain("server-held-token");
  });
});
