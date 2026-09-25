import { describe, expect, it } from "vitest";
import { validateCsrf } from "@/lib/csrf";
import type { BrowserSession } from "@/lib/session-service";

const session = { csrfToken: "csrf-value" } as BrowserSession;

describe("CSRF validation", () => {
  it("requires the exact origin and synchronizer token", () => {
    const valid = new Request("http://localhost:3001/api/incidents", {
      method: "POST",
      headers: {
        origin: "http://localhost:3001",
        "x-csrf-token": "csrf-value",
      },
    });
    expect(validateCsrf(valid, session, "http://localhost:3001")).toBe(true);
  });

  it.each([
    [{ origin: "http://localhost:3001" }, "missing token"],
    [{ "x-csrf-token": "csrf-value" }, "missing origin"],
    [
      { origin: "https://hostile.example", "x-csrf-token": "csrf-value" },
      "hostile origin",
    ],
    [
      { origin: "http://localhost:3001", "x-csrf-token": "stale" },
      "stale token",
    ],
  ] as Array<[Record<string, string>, string]>)("rejects %s (%s)", (headers) => {
    const request = new Request("http://localhost:3001/api/incidents", {
      method: "POST",
      headers,
    });
    expect(validateCsrf(request, session, "http://localhost:3001")).toBe(false);
  });
});
