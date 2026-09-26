import "server-only";

import { AsyncLocalStorage } from "node:async_hooks";
import { randomUUID } from "node:crypto";
import type { NextRequest } from "next/server";

const context = new AsyncLocalStorage<{ correlationId: string }>();
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const sensitiveKeys = /authorization|cookie|password|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|session/i;

type WebOperation = "bff_read" | "bff_mutation";

export function currentCorrelationId(): string | undefined {
  return context.getStore()?.correlationId;
}

export function correlationId(value: string | null): string {
  const candidate = value?.trim();
  return candidate && candidate.length <= 64 && uuidPattern.test(candidate)
    ? candidate.toLowerCase()
    : randomUUID();
}

export function withRequestTelemetry<T>(
  request: NextRequest,
  operation: (correlationId: string) => Promise<T>,
): Promise<T> {
  const id = correlationId(request.headers.get("x-correlation-id"));
  return context.run({ correlationId: id }, () => operation(id));
}

export function structuredLog(
  level: "info" | "warn" | "error",
  event: string,
  message: string,
  fields: Record<string, unknown> = {},
): void {
  const record = JSON.stringify(redact({
    timestamp: new Date().toISOString(),
    level,
    service: "web",
    environment: process.env.AIRA_ENV || "production",
    build_sha: process.env.AIRA_BUILD_SHA || "unknown",
    event,
    message,
    correlation_id: currentCorrelationId(),
    ...fields,
  }));
  (level === "error" ? console.error : level === "warn" ? console.warn : console.info)(record);
}

export function emitWebRequestMetrics(
  operation: WebOperation,
  status: number,
  durationMs: number,
): void {
  const statusClass = `${Math.floor(status / 100)}xx`;
  const result = status < 500 ? "succeeded" : "failed";
  emitMetric("request_count", 1, "Count", operation, result, statusClass);
  emitMetric("request_duration_ms", Math.max(0, durationMs), "Milliseconds", operation, result, statusClass);
  if (status >= 500) emitMetric("server_error_count", 1, "Count", operation, result, statusClass);
  if (status === 401) emitMetric("auth_failure_count", 1, "Count", operation, result, statusClass);
  if (status === 403) emitMetric("authorization_failure_count", 1, "Count", operation, result, statusClass);
}

function emitMetric(
  name: "request_count" | "request_duration_ms" | "server_error_count" | "auth_failure_count" | "authorization_failure_count",
  value: number,
  unit: "Count" | "Milliseconds",
  operation: WebOperation,
  result: "succeeded" | "failed",
  statusClass: string,
): void {
  const dimensions = {
    Environment: process.env.AIRA_ENV || "production",
    Service: "web",
    Operation: operation,
    Result: result,
    StatusClass: statusClass,
  };
  console.info(JSON.stringify({
    _aws: {
      Timestamp: Date.now(),
      CloudWatchMetrics: [{
        Namespace: "AIRA/Hosted",
        Dimensions: [Object.keys(dimensions), ["Environment", "Service"]],
        Metrics: [{ Name: name, Unit: unit }],
      }],
    },
    ...dimensions,
    [name]: value,
  }));
}

export function redact(value: unknown, key = ""): unknown {
  if (sensitiveKeys.test(key)) return "[REDACTED]";
  if (Array.isArray(value)) return value.map((item) => redact(item));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([name, item]) => [name, redact(item, name)]),
    );
  }
  if (typeof value !== "string") return value;
  return value
    .replace(/\bBearer\s+\S+/gi, "Bearer [REDACTED]")
    .replace(/([a-z][a-z0-9+.-]*:\/\/[^:/\s]+:)[^@\s]+@/gi, "$1[REDACTED]@")
    .replace(/\b(authorization|cookie|set-cookie):\s*\S+/gi, "$1: [REDACTED]")
    .replace(/https?:\/\/\S+[?&]X-Amz-(Signature|Credential)=\S+/gi, "[REDACTED_PRESIGNED_URL]");
}
