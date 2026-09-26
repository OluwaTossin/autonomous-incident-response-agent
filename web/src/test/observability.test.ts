import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  correlationId,
  emitWebRequestMetrics,
  redact,
  structuredLog,
  withRequestTelemetry,
} from "@/lib/observability";

afterEach(() => vi.restoreAllMocks());

describe("hosted web observability", () => {
  it("accepts only bounded UUID correlation values", async () => {
    const id = crypto.randomUUID();
    expect(correlationId(id.toUpperCase())).toBe(id);
    expect(correlationId("not-safe")).toMatch(/^[0-9a-f-]{36}$/);
    const request = new NextRequest("https://aira.example/api/incidents", {
      headers: { "x-correlation-id": id },
    });
    await expect(withRequestTelemetry(request, async (current) => current)).resolves.toBe(id);
  });

  it("redacts secrets in representative emitted records", async () => {
    const output = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const request = new NextRequest("https://aira.example/api/incidents");
    await withRequestTelemetry(request, async () => {
      structuredLog("warn", "auth.failed", "Bearer token-value", {
        cookie: "aira_session=secret",
        database_url: "postgresql://user:password@example/db",
        client_secret: "provider-secret",
        link: "https://bucket.s3.example/item?X-Amz-Signature=signature-secret",
      });
    });
    const record = JSON.parse(String(output.mock.calls[0][0]));
    const rendered = JSON.stringify(record);
    expect(record.cookie).toBe("[REDACTED]");
    expect(rendered).not.toContain("token-value");
    expect(rendered).not.toContain("password@example");
    expect(rendered).not.toContain("provider-secret");
    expect(rendered).not.toContain("signature-secret");
    expect(record.correlation_id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("redacts nested session and token fields", () => {
    expect(redact({ session: { accessToken: "secret" } })).toEqual({
      session: "[REDACTED]",
    });
  });

  it("emits only bounded web request dimensions", () => {
    const output = vi.spyOn(console, "info").mockImplementation(() => undefined);
    emitWebRequestMetrics("bff_mutation", 503, 42);
    const records = output.mock.calls.map(([value]) => JSON.parse(String(value)));
    expect(records.map((record) => Object.keys(record).sort())).toEqual(
      expect.arrayContaining([
        expect.arrayContaining(["Environment", "Operation", "Result", "Service", "StatusClass"]),
      ]),
    );
    expect(records.every((record) => record.Operation === "bff_mutation")).toBe(true);
    expect(JSON.stringify(records)).not.toMatch(/organization|workspace|incident|job_id/i);
  });
});
