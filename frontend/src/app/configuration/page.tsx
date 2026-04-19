"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Spinner } from "@/components/spinner";
import { adminPatchOperatorSettings } from "@/lib/admin-api";
import { ApiFailure } from "@/lib/api-errors";
import {
  getSessionAdminApiKey,
  publicAdminProxyInjectsHeaders,
  publicApiBase,
  setSessionAdminApiKey,
} from "@/lib/config";
import { getOperatorConfig, type OperatorConfig } from "@/lib/operator-api";

function formatErr(e: unknown): string {
  if (e instanceof ApiFailure) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

export default function ConfigurationPage() {
  const apiBase = useMemo(() => publicApiBase(), []);
  const proxyInjects = useMemo(() => publicAdminProxyInjectsHeaders(), []);
  const [cfg, setCfg] = useState<OperatorConfig | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);

  const [airaDataMode, setAiraDataMode] = useState<"demo" | "user">("demo");
  const [ragTopK, setRagTopK] = useState(8);
  const [llmTemp, setLlmTemp] = useState(0.2);
  const [llmModel, setLlmModel] = useState("");
  const [embedModel, setEmbedModel] = useState("");
  const [workspaceOnly, setWorkspaceOnly] = useState(false);
  const [adminKeyInput, setAdminKeyInput] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    setLoadErr(null);
    try {
      const c = await getOperatorConfig(apiBase);
      setCfg(c);
      setAiraDataMode(c.aira_data_mode === "user" ? "user" : "demo");
      setRagTopK(c.rag_top_k);
      setLlmTemp(c.llm_temperature);
      setLlmModel(c.llm_model);
      setEmbedModel(c.embedding_model);
      setWorkspaceOnly(c.rag_workspace_corpus_only);
    } catch (e) {
      setCfg(null);
      setLoadErr(formatErr(e));
    } finally {
      setBusy(false);
    }
  }, [apiBase]);

  useEffect(() => {
    void load();
  }, [load]);

  const saveOverrides = useCallback(async () => {
    const k = adminKeyInput.trim();
    if (k) setSessionAdminApiKey(k);
    if (!getSessionAdminApiKey() && !proxyInjects) {
      toast.error("Admin key required", {
        description: "Paste the admin key below, or enable proxy header injection at build time.",
      });
      return;
    }
    setSaving(true);
    try {
      await adminPatchOperatorSettings(apiBase, {
        aira_data_mode: airaDataMode,
        rag_top_k: ragTopK,
        llm_temperature: llmTemp,
        llm_model: llmModel.trim() || undefined,
        embedding_model: embedModel.trim() || undefined,
        rag_workspace_corpus_only: workspaceOnly,
      });
      setAdminKeyInput("");
      toast.success("Settings written", {
        description: "Merged into workspace config/operator_overrides.yaml (process env still wins).",
      });
      await load();
    } catch (e) {
      toast.error("Save failed", { description: formatErr(e) });
    } finally {
      setSaving(false);
    }
  }, [apiBase, airaDataMode, ragTopK, llmTemp, llmModel, embedModel, workspaceOnly, load, proxyInjects, adminKeyInput]);

  return (
    <div className="mx-auto max-w-7xl space-y-8 px-4 py-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          Configuration
        </h1>
        <p className="max-w-3xl text-sm text-zinc-600 dark:text-zinc-400">
          Read-only view uses your triage key (optional{" "}
          <code className="rounded bg-zinc-100 px-1 text-xs dark:bg-zinc-800">NEXT_PUBLIC_TRIAGE_API_KEY</code>{" "}
          at build time, or configure the API without a key for local-only use). Saving changes calls{" "}
          <code className="rounded bg-zinc-100 px-1 text-xs dark:bg-zinc-800">PATCH /admin/operator-settings</code>{" "}
          and requires the admin key in session or a proxy-injected header.
        </p>
      </header>

      {loadErr ? (
        <div
          role="alert"
          className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100"
        >
          <p className="font-medium">Could not load /operator-config</p>
          <p className="mt-1">{loadErr}</p>
          <button
            type="button"
            onClick={() => void load()}
            className="mt-3 rounded-lg bg-amber-900 px-3 py-1.5 text-xs font-medium text-white dark:bg-amber-200 dark:text-amber-950"
          >
            Retry
          </button>
        </div>
      ) : null}

      {busy && !cfg ? (
        <div className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-400">
          <Spinner className="h-4 w-4" />
          Loading…
        </div>
      ) : null}

      {cfg ? (
        <>
          <section className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
              Effective values
            </h2>
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-xs uppercase text-zinc-500">Workspace</dt>
                <dd className="font-mono text-zinc-900 dark:text-zinc-100">{cfg.workspace_id}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase text-zinc-500">Data mode</dt>
                <dd className="text-zinc-900 dark:text-zinc-100">{cfg.aira_data_mode}</dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-xs uppercase text-zinc-500">Workspace data dir</dt>
                <dd className="break-all font-mono text-xs text-zinc-800 dark:text-zinc-200">
                  {cfg.workspace_data_dir}
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-xs uppercase text-zinc-500">Index dir</dt>
                <dd className="break-all font-mono text-xs text-zinc-800 dark:text-zinc-200">
                  {cfg.workspace_index_dir}
                </dd>
              </div>
              <div>
                <dt className="text-xs uppercase text-zinc-500">Operator overrides file</dt>
                <dd className="break-all font-mono text-xs text-zinc-800 dark:text-zinc-200">
                  {cfg.operator_overrides_file}
                </dd>
              </div>
              <div>
                <dt className="text-xs uppercase text-zinc-500">Overrides active</dt>
                <dd className="text-zinc-900 dark:text-zinc-100">{cfg.operator_overrides_active ? "yes" : "no"}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase text-zinc-500">Admin routes</dt>
                <dd className="text-zinc-900 dark:text-zinc-100">{cfg.admin_routes_enabled ? "enabled" : "disabled"}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase text-zinc-500">Triage API key</dt>
                <dd className="text-zinc-900 dark:text-zinc-100">
                  {cfg.triage_api_key_configured ? "required" : "not set"}
                </dd>
              </div>
            </dl>
          </section>

          <section className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
            <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-zinc-500">
              Edit (persisted to operator overrides)
            </h2>
            <p className="mb-4 text-xs text-zinc-500 dark:text-zinc-400">
              Secrets and provider keys are not editable here — use{" "}
              <code className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">.env</code> / deployment env.
            </p>

            {!proxyInjects ? (
              <div className="mb-4 max-w-xl">
                <label className="mb-1 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  Admin key (only if saving; optional if already in sessionStorage)
                </label>
                <input
                  type="password"
                  autoComplete="off"
                  value={adminKeyInput}
                  onChange={(e) => setAdminKeyInput(e.target.value)}
                  className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-900"
                  placeholder="Leave blank if you already saved it on the Setup page"
                />
              </div>
            ) : null}

            <div className="grid max-w-xl flex-col gap-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  AIRA_DATA_MODE
                </label>
                <select
                  value={airaDataMode}
                  onChange={(e) => setAiraDataMode(e.target.value as "demo" | "user")}
                  className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-900"
                >
                  <option value="demo">demo (sample corpus when workspace empty)</option>
                  <option value="user">user (workspace data only)</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  RAG_TOP_K ({ragTopK})
                </label>
                <input
                  type="number"
                  min={1}
                  max={64}
                  value={ragTopK}
                  onChange={(e) => setRagTopK(Number.parseInt(e.target.value, 10) || 1)}
                  className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-900"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  LLM_TEMPERATURE
                </label>
                <input
                  type="number"
                  step="0.05"
                  min={0}
                  max={2}
                  value={llmTemp}
                  onChange={(e) => setLlmTemp(Number.parseFloat(e.target.value) || 0)}
                  className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-900"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  LLM_MODEL
                </label>
                <input
                  value={llmModel}
                  onChange={(e) => setLlmModel(e.target.value)}
                  className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-900"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  EMBEDDING_MODEL
                </label>
                <input
                  value={embedModel}
                  onChange={(e) => setEmbedModel(e.target.value)}
                  className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-900"
                />
              </div>
              <label className="flex items-center gap-2 text-sm text-zinc-800 dark:text-zinc-200">
                <input
                  type="checkbox"
                  checked={workspaceOnly}
                  onChange={(e) => setWorkspaceOnly(e.target.checked)}
                  className="rounded border-zinc-400"
                />
                RAG_WORKSPACE_ONLY (corpus only from workspace data/)
              </label>
              <button
                type="button"
                disabled={saving}
                onClick={() => void saveOverrides()}
                className="inline-flex max-w-xs items-center justify-center gap-2 rounded-lg bg-violet-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
              >
                {saving ? (
                  <>
                    <Spinner className="h-4 w-4 text-white" />
                    Saving…
                  </>
                ) : (
                  "Save to workspace overrides"
                )}
              </button>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
