"use client";

import { useEffect } from "react";
import { toast } from "sonner";
import type { EvidenceItem } from "@/lib/types";

type Props = {
  item: EvidenceItem | null;
  onClose: () => void;
};

export function EvidenceFullContextModal({ item, onClose }: Props) {
  useEffect(() => {
    if (!item) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [item, onClose]);

  if (!item) return null;

  const block = [
    `type: ${item.type}`,
    `source: ${item.source}`,
    "",
    item.reason,
  ].join("\n");

  const copy = () => {
    void navigator.clipboard.writeText(block).then(
      () => toast.success("Evidence context copied"),
      () => toast.error("Copy failed"),
    );
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-[2px]"
      role="presentation"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="evidence-modal-title"
        className="max-h-[min(85vh,720px)] w-full max-w-2xl overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-2xl dark:border-zinc-700 dark:bg-zinc-950"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
          <h3
            id="evidence-modal-title"
            className="text-sm font-semibold text-zinc-900 dark:text-zinc-100"
          >
            Full evidence context
          </h3>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={copy}
              className="rounded-md bg-zinc-100 px-2.5 py-1 text-xs font-medium text-zinc-800 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700"
            >
              Copy all
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md px-2.5 py-1 text-xs font-medium text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
            >
              Close
            </button>
          </div>
        </div>
        <div className="max-h-[min(65vh,560px)] overflow-auto p-4">
          <dl className="space-y-3 text-sm">
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Type</dt>
              <dd className="mt-0.5 font-mono text-violet-700 dark:text-violet-300">{item.type}</dd>
            </div>
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wide text-zinc-500">Source</dt>
              <dd className="mt-0.5 break-all font-mono text-xs text-zinc-800 dark:text-zinc-200">
                {item.source}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
                Reason / excerpt
              </dt>
              <dd className="mt-1 whitespace-pre-wrap rounded-lg bg-zinc-50 p-3 font-mono text-xs leading-relaxed text-zinc-800 dark:bg-zinc-900 dark:text-zinc-200">
                {item.reason}
              </dd>
            </div>
          </dl>
        </div>
      </div>
    </div>
  );
}
