"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Spinner } from "@/components/spinner";
import {
  adminIndexStatus,
  adminListFiles,
  adminReindex,
  adminUpload,
} from "@/lib/admin-api";
import { ApiFailure } from "@/lib/api-errors";
import {
  clearSessionAdminApiKey,
  getSessionAdminApiKey,
  publicAdminProxyInjectsHeaders,
  publicApiBase,
  setSessionAdminApiKey,
} from "@/lib/config";

const CATEGORIES = ["runbooks", "incidents", "logs", "knowledge_base"] as const;

function formatErr(e: unknown): string {
  if (e instanceof ApiFailure) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

export default function SetupPage() {
  const apiBase = useMemo(() => publicApiBase(), []);
  const proxyInjects = useMemo(() => publicAdminProxyInjectsHeaders(), []);
  const [adminInput, setAdminInput] = useState("");
  const [hasStoredAdmin, setHasStoredAdmin] = useState(false);
  const [category, setCategory] = useState<(typeof CATEGORIES)[number]>("runbooks");
  const [files, setFiles] = useState<{ path: string; size_bytes: number }[]>([]);
  const [filesBusy, setFilesBusy] = useState(false);
  const [reindexBusy, setReindexBusy] = useState(false);
  const [indexPhase, setIndexPhase] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  useEffect(() => {
    setHasStoredAdmin(Boolean(getSessionAdminApiKey()) || proxyInjects);
  }, [proxyInjects]);

  const refreshFiles = useCallback(async () => {
    setFilesBusy(true);
    try {
      const list = await adminListFiles(apiBase);
      setFiles(list);
    } catch (e) {
      toast.error("Could not list files", { description: formatErr(e) });
    } finally {
      setFilesBusy(false);
    }
  }, [apiBase]);

  useEffect(() => {
    if (hasStoredAdmin || proxyInjects) void refreshFiles();
  }, [hasStoredAdmin, proxyInjects, refreshFiles]);

  const saveAdminKey = useCallback(() => {
    const v = adminInput.trim();
    if (!v) {
      toast.warning("Paste the admin key first");
      return;
    }
    setSessionAdminApiKey(v);
    setAdminInput("");
    setHasStoredAdmin(true);
    toast.success("Admin key saved for this browser session", {
      description: "Stored in sessionStorage only — not in the static bundle.",
    });
    void refreshFiles();
  }, [adminInput, refreshFiles]);

  const clearAdminKey = useCallback(() => {
    clearSessionAdminApiKey();
    setHasStoredAdmin(proxyInjects);
    toast.message("Admin key cleared from this tab");
  }, [proxyInjects]);

  const onUploadFile = useCallback(
    async (file: File) => {
      try {
        const out = await adminUpload(apiBase, category, file);
        toast.success("Uploaded", { description: `${out.path} (${out.size_bytes} bytes)` });
        await refreshFiles();
      } catch (e) {
        toast.error("Upload failed", { description: formatErr(e) });
      }
    },
    [apiBase, category, refreshFiles],
  );

  const runReindex = useCallback(async () => {
    setReindexBusy(true);
    setIndexPhase("starting");
    try {
      const out = await adminReindex(apiBase);
      toast.success(out.message || "Reindex finished");
      const st = await adminIndexStatus(apiBase);
      setIndexPhase(st.phase);
    } catch (e) {
      toast.error("Reindex failed", { description: formatErr(e) });
      try {
        const st = await adminIndexStatus(apiBase);
        setIndexPhase(st.phase);
      } catch {
        setIndexPhase(null);
      }
    } finally {
      setReindexBusy(false);
    }
  }, [apiBase]);

  const pollStatus = useCallback(async () => {
    try {
      const st = await adminIndexStatus(apiBase);
      setIndexPhase(st.phase);
    } catch {
      setIndexPhase(null);
    }
  }, [apiBase]);

  useEffect(() => {
    if (!hasStoredAdmin && !proxyInjects) return;
    const t = setInterval(() => void pollStatus(), 4000);
    void pollStatus();
    return () => clearInterval(t);
  }, [hasStoredAdmin, proxyInjects, pollStatus]);

  return (
    <div className="mx-auto max-w-7xl space-y-8 px-4 py-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          Setup
        </h1>
        <p className="max-w-3xl text-sm text-zinc-600 dark:text-zinc-400">
          Upload corpus files, inspect what is on disk under the active workspace, and rebuild the
          FAISS index. Admin routes require authentication — use a same-origin reverse proxy that
          injects headers, or paste the admin key once per session (stored in{" "}
          <code className="rounded bg-zinc-100 px-1 text-xs dark:bg-zinc-800">sessionStorage</code>
          , never embedded at build time).
        </p>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          API base ·{" "}
          <span className="break-all font-mono text-violet-600 dark:text-violet-400">{apiBase}</span>
        </p>
      </header>

      <section className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
          Admin authentication
        </h2>
        {proxyInjects ? (
          <p className="text-sm text-zinc-700 dark:text-zinc-200">
            Build flag <code className="rounded bg-zinc-100 px-1 text-xs dark:bg-zinc-800">NEXT_PUBLIC_ADMIN_PROXY_INJECTS_HEADERS</code>{" "}
            is enabled — requests omit the admin header; your edge proxy must add{" "}
            <code className="rounded bg-zinc-100 px-1 text-xs dark:bg-zinc-800">x-admin-api-key</code>.
          </p>
        ) : (
          <div className="flex max-w-xl flex-col gap-3 sm:flex-row sm:items-end">
            <div className="min-w-0 flex-1">
              <label className="mb-1 block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                Admin key (session only)
              </label>
              <input
                type="password"
                autoComplete="off"
                value={adminInput}
                onChange={(e) => setAdminInput(e.target.value)}
                placeholder="Paste key, then Save"
                className="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-600 dark:bg-zinc-900"
              />
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => saveAdminKey()}
                className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500"
              >
                Save to session
              </button>
              <button
                type="button"
                onClick={() => clearAdminKey()}
                className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-800 hover:bg-zinc-50 dark:border-zinc-600 dark:text-zinc-100 dark:hover:bg-zinc-900"
              >
                Clear
              </button>
            </div>
          </div>
        )}
        {!proxyInjects && hasStoredAdmin ? (
          <p className="mt-2 text-xs text-emerald-700 dark:text-emerald-300">
            Admin key is present in this tab (sessionStorage).
          </p>
        ) : null}
      </section>

      <section className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
          Upload
        </h2>
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <label className="text-sm text-zinc-600 dark:text-zinc-400">Category</label>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value as (typeof CATEGORIES)[number])}
            className="rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm dark:border-zinc-600 dark:bg-zinc-900"
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        <div
          role="button"
          tabIndex={0}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            const f = e.dataTransfer.files?.[0];
            if (f) void onUploadFile(f);
          }}
          className={`flex min-h-[140px] cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 py-8 text-center transition ${
            dragOver
              ? "border-violet-500 bg-violet-50 dark:bg-violet-950/30"
              : "border-zinc-300 bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-900/40"
          }`}
        >
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            Drag and drop a file here, or choose one
          </p>
          <input
            type="file"
            className="mt-4 block text-sm text-zinc-600 file:mr-3 file:rounded-lg file:border-0 file:bg-violet-600 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-white hover:file:bg-violet-500 dark:text-zinc-400"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void onUploadFile(f);
              e.target.value = "";
            }}
          />
        </div>
      </section>

      <section className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">
            Workspace files
          </h2>
          <button
            type="button"
            onClick={() => void refreshFiles()}
            disabled={filesBusy || (!hasStoredAdmin && !proxyInjects)}
            className="rounded-lg border border-zinc-300 px-3 py-1.5 text-sm font-medium hover:bg-zinc-50 disabled:opacity-40 dark:border-zinc-600 dark:hover:bg-zinc-900"
          >
            {filesBusy ? "Refreshing…" : "Refresh"}
          </button>
        </div>
        {!hasStoredAdmin && !proxyInjects ? (
          <p className="text-sm text-zinc-500">Save an admin key (or enable proxy injection) to list files.</p>
        ) : files.length === 0 ? (
          <p className="text-sm text-zinc-500">No corpus files yet under workspace data/.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-zinc-200 text-xs uppercase text-zinc-500 dark:border-zinc-700">
                  <th className="py-2 pe-4 font-medium">Path</th>
                  <th className="py-2 font-medium">Size</th>
                </tr>
              </thead>
              <tbody>
                {files.map((f) => (
                  <tr key={f.path} className="border-b border-zinc-100 dark:border-zinc-800">
                    <td className="py-2 pe-4 font-mono text-xs text-zinc-800 dark:text-zinc-200">
                      {f.path}
                    </td>
                    <td className="py-2 text-zinc-600 dark:text-zinc-400">{f.size_bytes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-950">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
          Reindex
        </h2>
        <p className="mb-4 text-sm text-zinc-600 dark:text-zinc-400">
          Runs the same index build as the CLI. Large corpora can take several minutes; only one run
          at a time is allowed on the server.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void runReindex()}
            disabled={reindexBusy || (!hasStoredAdmin && !proxyInjects)}
            className="inline-flex items-center gap-2 rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800 disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
          >
            {reindexBusy ? (
              <>
                <Spinner className="h-4 w-4" />
                Reindexing…
              </>
            ) : (
              "Rebuild index"
            )}
          </button>
          {indexPhase ? (
            <span className="text-sm text-zinc-600 dark:text-zinc-400">
              Last status phase: <strong className="text-zinc-900 dark:text-zinc-100">{indexPhase}</strong>
            </span>
          ) : null}
        </div>
      </section>
    </div>
  );
}
