"use client";

import { FormEvent, useState } from "react";
import { LoaderCircle, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import type { BrowserError, WorkspaceDetail } from "@/lib/types";

export function WorkspaceCreateForm({ organizationId, csrfToken }: { organizationId: string; csrfToken: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setError(null);
    const form = new FormData(event.currentTarget);
    try {
      const response = await fetch(`/api/organizations/${encodeURIComponent(organizationId)}/workspaces`, {
        method: "POST",
        headers: { "content-type": "application/json", "x-csrf-token": csrfToken },
        body: JSON.stringify({ name: form.get("name"), slug: form.get("slug"), description: form.get("description") || null }),
      });
      const payload = (await response.json()) as WorkspaceDetail | BrowserError;
      if (response.status === 401) return window.location.assign("/auth/login?returnTo=%2Fapp");
      if (!response.ok) throw new Error(browserError(payload));
      const detail = payload as WorkspaceDetail;
      router.push(`/app/orgs/${organizationId}/workspaces/${detail.workspace.workspace_id}`);
      router.refresh();
    } catch (caught) { setError(message(caught)); }
    finally { setBusy(false); }
  }

  return (
    <form className="workspace-create" onSubmit={submit}>
      <div className="field-row">
        <label>Name<input name="name" required maxLength={200} placeholder="Production operations" /></label>
        <label>Slug<input name="slug" required maxLength={100} pattern="[a-z0-9][a-z0-9-]*" placeholder="production-ops" /></label>
      </div>
      <label>Description<textarea name="description" maxLength={1000} rows={3} placeholder="What this workspace owns and monitors." /></label>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      <button className="primary-command" disabled={busy} type="submit">
        {busy ? <LoaderCircle className="spin" aria-hidden="true" size={18} /> : <Plus aria-hidden="true" size={18} />}
        {busy ? "Creating" : "Create workspace"}
      </button>
    </form>
  );
}

function browserError(payload: unknown): string {
  return payload && typeof payload === "object" && "error" in payload ? (payload as BrowserError).error.message : "The request could not be completed.";
}
function message(error: unknown): string { return error instanceof Error ? error.message : "The request could not be completed."; }
