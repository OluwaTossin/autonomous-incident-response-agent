import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { BrowserSession } from "@/lib/session-service";

const mocks = vi.hoisted(() => ({
  approve: vi.fn(),
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
    api: { approveApproval: mocks.approve },
    sessions: { load: mocks.load, revoke: mocks.revoke },
  }),
}));

import { POST } from "@/app/api/approvals/[approvalId]/approve/route";

const session = {
  accessToken: "server-held-token",
  csrfToken: "csrf-value",
} as BrowserSession;

function request(headers: Record<string, string> = {}) {
  return new NextRequest("https://aira.example/api/approvals/approval-1/approve", {
    method: "POST",
    headers: {
      cookie: "aira_session=opaque-id",
      "content-type": "application/json",
      ...headers,
    },
    body: JSON.stringify({
      organization_id: "org-1",
      workspace_id: "workspace-1",
      reason: "Reviewed",
    }),
  });
}

beforeEach(() => {
  mocks.approve.mockReset().mockResolvedValue({ state: "approved" });
  mocks.load.mockReset().mockResolvedValue(session);
  mocks.revoke.mockReset().mockResolvedValue(undefined);
});

describe("approval mutation BFF", () => {
  it.each<{ headers: Record<string, string>; label: string }>([
    { headers: {}, label: "missing verification" },
    {
      headers: {
        origin: "https://hostile.example",
        "x-csrf-token": "csrf-value",
      },
      label: "cross-origin request",
    },
    {
      headers: { origin: "https://aira.example", "x-csrf-token": "stale" },
      label: "stale token",
    },
  ])("rejects $label", async ({ headers }) => {
    const response = await POST(request(headers), {
      params: Promise.resolve({ approvalId: "approval-1" }),
    });

    expect(response.status).toBe(403);
    expect(mocks.approve).not.toHaveBeenCalled();
  });

  it("uses the authenticated server session for an approved mutation", async () => {
    const response = await POST(
      request({
        origin: "https://aira.example",
        "x-csrf-token": "csrf-value",
      }),
      { params: Promise.resolve({ approvalId: "approval-1" }) },
    );

    expect(response.status).toBe(200);
    expect(mocks.approve).toHaveBeenCalledWith(
      "server-held-token",
      "org-1",
      "workspace-1",
      "approval-1",
      "Reviewed",
    );
    expect(await response.text()).not.toContain("server-held-token");
  });
});
