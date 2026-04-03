import { ApiFailure } from "./api-errors";
import {
  publicFeedbackTimeoutMs,
  publicTriageApiKey,
  publicTriageTimeoutMs,
} from "./config";
import type { TriageResponse } from "./types";
import { isTriageResponse } from "./types";

function jsonHeaders(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  const key = publicTriageApiKey();
  if (key) h["x-api-key"] = key;
  return h;
}

function formatErrorDetail(data: unknown): string {
  if (!data || typeof data !== "object") return "Request failed";
  const d = data as Record<string, unknown>;
  const detail = d.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((e) => {
        if (e && typeof e === "object" && "msg" in e) {
          return String((e as { msg?: string }).msg ?? e);
        }
        return JSON.stringify(e);
      })
      .join("; ");
  }
  return JSON.stringify(data);
}

export async function postTriage(
  baseUrl: string,
  incident: Record<string, unknown>,
): Promise<TriageResponse> {
  const timeoutMs = publicTriageTimeoutMs();
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);
  let r: Response;
  try {
    r = await fetch(`${baseUrl}/triage`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(incident),
      signal: controller.signal,
    });
  } catch (e) {
    if (e instanceof Error && e.name === "AbortError") {
      throw new ApiFailure(
        `Request timed out after ${Math.round(timeoutMs / 1000)}s (triage + LLM). Check API health or increase NEXT_PUBLIC_TRIAGE_TIMEOUT_MS.`,
        "timeout",
      );
    }
    throw new ApiFailure(
      e instanceof Error ? e.message : "Network error — is the API reachable?",
      "network",
    );
  } finally {
    clearTimeout(id);
  }

  const text = await r.text();
  if (!text?.trim()) {
    throw new ApiFailure("Empty response from API", "empty_body", r.status);
  }
  let data: unknown;
  try {
    data = JSON.parse(text) as unknown;
  } catch {
    throw new ApiFailure(
      "Response was not valid JSON (malformed body or proxy HTML error page).",
      "invalid_json",
      r.status,
    );
  }
  if (!r.ok) {
    throw new ApiFailure(formatErrorDetail(data), "http", r.status);
  }
  if (!isTriageResponse(data)) {
    throw new ApiFailure(
      "Response JSON did not match expected triage shape (missing triage_id or core fields).",
      "malformed_response",
      r.status,
    );
  }
  return data;
}

export async function postTriageFeedback(
  baseUrl: string,
  payload: {
    triage_id: string;
    diagnosis_correct: boolean;
    actions_useful: boolean;
    notes: string;
  },
): Promise<void> {
  const timeoutMs = publicFeedbackTimeoutMs();
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);
  let r: Response;
  try {
    r = await fetch(`${baseUrl}/n8n/triage-feedback`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
  } catch (e) {
    if (e instanceof Error && e.name === "AbortError") {
      throw new ApiFailure("Feedback request timed out.", "timeout");
    }
    throw new ApiFailure(
      e instanceof Error ? e.message : "Network error submitting feedback.",
      "network",
    );
  } finally {
    clearTimeout(id);
  }

  const text = await r.text();
  let data: unknown = {};
  if (text?.trim()) {
    try {
      data = JSON.parse(text) as unknown;
    } catch {
      throw new ApiFailure("Feedback response was not valid JSON.", "invalid_json", r.status);
    }
  }
  if (!r.ok) {
    throw new ApiFailure(formatErrorDetail(data), "http", r.status);
  }
  const st = (data as { status?: string }).status;
  if (st && st !== "logged" && st !== "skipped") {
    throw new ApiFailure(`Unexpected feedback status: ${st}`, "malformed_response", r.status);
  }
}
