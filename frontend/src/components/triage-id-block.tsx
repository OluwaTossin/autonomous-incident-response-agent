"use client";

import { toast } from "sonner";

type Props = {
  triageId: string;
};

export function TriageIdBlock({ triageId }: Props) {
  const copy = () => {
    if (!triageId) return;
    void navigator.clipboard.writeText(triageId).then(
      () => toast.success("triage_id copied"),
      () => toast.error("Could not copy to clipboard"),
    );
  };

  return (
    <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-700 dark:bg-zinc-900/50">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          Triage ID
        </span>
        <button
          type="button"
          onClick={copy}
          className="rounded-md bg-white px-2.5 py-1 text-xs font-medium text-violet-700 ring-1 ring-zinc-200 hover:bg-zinc-50 dark:bg-zinc-800 dark:text-violet-300 dark:ring-zinc-600 dark:hover:bg-zinc-700"
        >
          Copy
        </button>
      </div>
      <code className="mt-2 block break-all rounded bg-white px-2 py-1.5 font-mono text-xs text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
        {triageId}
      </code>
      <p className="mt-1.5 text-xs text-zinc-500 dark:text-zinc-400">
        Joins feedback and audit JSONL (same as Gradio / n8n).
      </p>
    </div>
  );
}
