"use client";

import { useState } from "react";
import { Play, RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import type { BrowserError, Incident, TriageAccepted } from "@/lib/types";

export function IncidentActions({
  organizationId,
  workspaceId,
  incidentId,
  state,
  csrfToken,
}: {
  organizationId: string;
  workspaceId: string;
  incidentId: string;
  state: string;
  csrfToken: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scope = `organization_id=${encodeURIComponent(organizationId)}&workspace_id=${encodeURIComponent(workspaceId)}`;

  async function transition(next: "investigating" | "resolved" | "closed") {
    setBusy(next);
    setError(null);
    try {
      await mutate<Incident>(
        `/api/incidents/${encodeURIComponent(incidentId)}?${scope}`,
        "PATCH",
        { state: next },
        csrfToken,
      );
      router.refresh();
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(null);
    }
  }

  async function retriage() {
    setBusy("triage");
    setError(null);
    try {
      const accepted = await mutate<TriageAccepted>(
        `/api/incidents/${encodeURIComponent(incidentId)}/triage`,
        "POST",
        {
          organization_id: organizationId,
          workspace_id: workspaceId,
          idempotency_key: crypto.randomUUID(),
        },
        csrfToken,
      );
      router.push(
        `/app/orgs/${organizationId}/workspaces/${workspaceId}/incidents/${incidentId}/triage/${accepted.triage_run_id}`,
      );
    } catch (caught) {
      setError(message(caught));
      setBusy(null);
    }
  }

  const targets = state === "open"
    ? (["investigating", "resolved", "closed"] as const)
    : state === "investigating"
      ? (["resolved", "closed"] as const)
      : state === "resolved"
        ? (["closed"] as const)
        : [];
  return (
    <div className="incident-actions">
      <button className="primary-command" type="button" disabled={busy !== null} onClick={() => void retriage()}>
        {busy === "triage" ? <RefreshCw className="spin" aria-hidden="true" size={17} /> : <Play aria-hidden="true" size={17} />}
        Run triage
      </button>
      {targets.map((target) => (
        <button className="icon-command" type="button" disabled={busy !== null} key={target} onClick={() => void transition(target)}>
          Mark {target}
        </button>
      ))}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
    </div>
  );
}

async function mutate<T>(url: string, method: string, body: unknown, csrfToken: string): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: { "content-type": "application/json", "x-csrf-token": csrfToken },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (response.status === 401) window.location.assign("/auth/login?returnTo=%2Fapp");
  const payload = (await response.json()) as T | BrowserError;
  if (!response.ok) throw new Error(errorMessage(payload));
  return payload as T;
}

function errorMessage(payload: unknown): string {
  return payload && typeof payload === "object" && "error" in payload
    ? (payload as BrowserError).error.message
    : "The request could not be completed.";
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : "The request could not be completed.";
}
