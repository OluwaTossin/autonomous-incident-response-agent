"use client";

import { FormEvent, useState } from "react";
import { Archive, LoaderCircle, RefreshCw, Save } from "lucide-react";
import { useRouter } from "next/navigation";
import type { BrowserError, WorkspaceDetail, WorkspaceSummary } from "@/lib/types";

export function WorkspaceSettingsForm({ detail, csrfToken }: { detail: WorkspaceDetail; csrfToken: string }) {
  const router = useRouter();
  const { workspace, configuration } = detail;
  const [busy, setBusy] = useState<"metadata" | "configuration" | "archive" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const base = `/api/organizations/${encodeURIComponent(workspace.organization_id)}/workspaces/${encodeURIComponent(workspace.workspace_id)}`;

  async function mutate<T>(url: string, method: string, body: unknown): Promise<T> {
    const response = await fetch(url, { method, headers: { "content-type": "application/json", "x-csrf-token": csrfToken }, body: JSON.stringify(body), cache: "no-store" });
    const payload = (await response.json()) as T | BrowserError;
    if (response.status === 401) { window.location.assign("/auth/login?returnTo=%2Fapp"); throw new Error("Session expired"); }
    if (response.status === 409) setConflict(true);
    if (!response.ok) throw new Error(browserError(payload));
    return payload as T;
  }

  async function saveMetadata(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("metadata"); setNotice(null); setConflict(false);
    const form = new FormData(event.currentTarget);
    try {
      await mutate<WorkspaceDetail>(base, "PATCH", { expected_version: workspace.version, name: form.get("name"), slug: form.get("slug"), description: form.get("description") || null });
      setNotice("Workspace details updated."); router.refresh();
    } catch (error) { setNotice(message(error)); }
    finally { setBusy(null); }
  }

  async function saveConfiguration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("configuration"); setNotice(null); setConflict(false);
    const form = new FormData(event.currentTarget);
    try {
      await mutate<WorkspaceDetail>(`${base}/configuration`, "PATCH", { expected_version: configuration.version, rag_top_k: Number(form.get("rag_top_k")), llm_temperature: Number(form.get("llm_temperature")) });
      setNotice("Triage configuration updated."); router.refresh();
    } catch (error) { setNotice(message(error)); }
    finally { setBusy(null); }
  }

  async function archiveWorkspace() {
    if (!window.confirm(`Archive ${workspace.name}? New operational work will be blocked and this cannot be undone here.`)) return;
    setBusy("archive"); setNotice(null); setConflict(false);
    try {
      await mutate<WorkspaceSummary>(`${base}/archive`, "POST", { expected_version: workspace.version });
      router.push(`/app/orgs/${workspace.organization_id}/workspaces?archived=1`); router.refresh();
    } catch (error) { setNotice(message(error)); setBusy(null); }
  }

  return (
    <div className="settings-stack">
      {notice ? <div className={conflict ? "inline-notice conflict" : "inline-notice"} role="status"><span>{notice}</span>{conflict ? <button type="button" className="icon-command" onClick={() => window.location.reload()}><RefreshCw aria-hidden="true" size={16} />Reload current values</button> : null}</div> : null}
      <section className="settings-section" aria-labelledby="workspace-details-title">
        <div className="section-heading"><div><span className="eyebrow">Identity</span><h2 id="workspace-details-title">Workspace details</h2></div></div>
        <form className="settings-form" onSubmit={saveMetadata}>
          <div className="field-row"><label>Name<input name="name" required maxLength={200} defaultValue={workspace.name} /></label><label>Slug<input name="slug" required maxLength={100} pattern="[a-z0-9][a-z0-9-]*" defaultValue={workspace.slug} /></label></div>
          <label>Description<textarea name="description" maxLength={1000} rows={4} defaultValue={workspace.description || ""} /></label>
          <button className="primary-command" disabled={busy !== null} type="submit">{busy === "metadata" ? <LoaderCircle className="spin" aria-hidden="true" size={18} /> : <Save aria-hidden="true" size={18} />}Save details</button>
        </form>
      </section>
      <section className="settings-section" aria-labelledby="configuration-title">
        <div className="section-heading"><div><span className="eyebrow">Triage defaults</span><h2 id="configuration-title">Configuration</h2></div></div>
        <form className="settings-form" onSubmit={saveConfiguration}>
          <label>Retrieval results<input name="rag_top_k" type="number" min={1} max={64} step={1} required defaultValue={configuration.rag_top_k} /><small>Maximum knowledge passages considered per triage, from 1 to 64.</small></label>
          <label>LLM temperature<input name="llm_temperature" type="number" min={0} max={2} step={0.1} required defaultValue={configuration.llm_temperature} /><small>Generation variability from 0 to 2.</small></label>
          <button className="primary-command" disabled={busy !== null} type="submit">{busy === "configuration" ? <LoaderCircle className="spin" aria-hidden="true" size={18} /> : <Save aria-hidden="true" size={18} />}Save configuration</button>
        </form>
      </section>
      <section className="danger-zone" aria-labelledby="archive-title"><div><h2 id="archive-title">Archive workspace</h2><p>Preserve historical records while blocking new operational work. Restore is not available in V3.14.</p></div><button className="icon-command danger" disabled={busy !== null} onClick={() => void archiveWorkspace()} type="button"><Archive aria-hidden="true" size={17} />{busy === "archive" ? "Archiving" : "Archive"}</button></section>
    </div>
  );
}

function browserError(payload: unknown): string { return payload && typeof payload === "object" && "error" in payload ? (payload as BrowserError).error.message : "The request could not be completed."; }
function message(error: unknown): string { return error instanceof Error ? error.message : "The request could not be completed."; }
