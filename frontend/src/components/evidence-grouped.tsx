"use client";

import { useState } from "react";
import { EvidenceFullContextModal } from "@/components/evidence-full-context-modal";
import { EVIDENCE_SECTIONS, groupEvidence } from "@/lib/evidence-groups";
import type { EvidenceItem } from "@/lib/types";

const SNIPPET_CHARS = 220;

type Props = {
  items: EvidenceItem[];
};

function EvidenceRow({
  ev,
  rowKey,
  onOpenFull,
}: {
  ev: EvidenceItem;
  rowKey: string;
  onOpenFull: () => void;
}) {
  const [snippetExpanded, setSnippetExpanded] = useState(false);
  const reason = ev.reason ?? "";
  const lines = reason.split("\n");
  const longByLines = lines.length > 5;
  const longByChars = reason.length > SNIPPET_CHARS;
  const needsSnippet = longByLines || longByChars;

  let display = reason;
  if (needsSnippet && !snippetExpanded) {
    if (longByLines) {
      display = `${lines.slice(0, 5).join("\n")}\n… ${lines.length - 5} more line(s) — expand below or open full context`;
    } else {
      display = `${reason.slice(0, SNIPPET_CHARS).trimEnd()}…`;
    }
  }

  const displayLines = display.split("\n");

  return (
    <li className="list-none border-t border-zinc-200 py-3 first:border-t-0 first:pt-0 dark:border-zinc-700">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <code className="rounded bg-zinc-200 px-1.5 py-0.5 text-xs dark:bg-zinc-800">{ev.source}</code>
        <span className="font-mono text-[10px] uppercase text-zinc-400">{ev.type}</span>
      </div>
      <div className="mt-2 space-y-1">
        {displayLines.map((line, i) => (
          <div
            key={`${rowKey}-L${i}`}
            className="rounded-md border border-zinc-100 bg-white/80 px-2 py-1.5 font-mono text-[12px] leading-snug text-zinc-700 dark:border-zinc-800 dark:bg-zinc-950/50 dark:text-zinc-300"
          >
            {line || "\u00a0"}
          </div>
        ))}
      </div>
      {needsSnippet ? (
        <button
          type="button"
          onClick={() => setSnippetExpanded((v) => !v)}
          className="mt-2 text-xs font-medium text-violet-600 hover:text-violet-500 dark:text-violet-400"
        >
          {snippetExpanded ? "Collapse snippet" : "Expand snippet"}
        </button>
      ) : null}
      <button
        type="button"
        onClick={onOpenFull}
        className="mt-2 block text-xs font-semibold text-violet-700 underline decoration-violet-400/50 underline-offset-2 hover:text-violet-600 dark:text-violet-300"
      >
        View full context
      </button>
    </li>
  );
}

/** Collapsible sections + per-row drill-down (Gradio grouping + operator depth). */
export function EvidenceGrouped({ items }: Props) {
  const [modalItem, setModalItem] = useState<EvidenceItem | null>(null);

  if (!items.length) {
    return (
      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        No structured evidence rows (RAG may still have influenced the model).
      </p>
    );
  }

  const groups = groupEvidence(items);
  const visible = EVIDENCE_SECTIONS.filter((s) => (groups[s.key]?.length ?? 0) > 0);

  if (!visible.length) {
    return (
      <p className="text-sm text-zinc-500 dark:text-zinc-400">No structured evidence rows.</p>
    );
  }

  return (
    <>
      <div className="space-y-2.5 font-sans">
        {visible.map(({ key, title, hint }) => {
          const sectionItems = groups[key];
          return (
            <details
              key={key}
              className="rounded-[10px] border border-zinc-200 bg-zinc-50 px-3.5 dark:border-zinc-700 dark:bg-zinc-900/40"
            >
              <summary className="cursor-pointer list-none py-3 font-semibold text-zinc-900 marker:hidden dark:text-zinc-100 [&::-webkit-details-marker]:hidden">
                <span className="inline-flex flex-wrap items-baseline gap-x-2">
                  {title}
                  <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
                    ({sectionItems.length}) · {hint}
                  </span>
                </span>
              </summary>
              <ul className="border-t border-zinc-200 pb-3.5 pt-1 dark:border-zinc-700">
                {sectionItems.map((ev, i) => (
                  <EvidenceRow
                    key={`${key}-${ev.source}-${i}`}
                    ev={ev}
                    rowKey={`${key}-${i}`}
                    onOpenFull={() => setModalItem(ev)}
                  />
                ))}
              </ul>
            </details>
          );
        })}
      </div>
      <EvidenceFullContextModal item={modalItem} onClose={() => setModalItem(null)} />
    </>
  );
}
