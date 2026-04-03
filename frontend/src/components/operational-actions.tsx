"use client";

import { Fragment, type ReactNode } from "react";
import { runbookDocsBaseUrl } from "@/lib/config";

const URL_RE = /(https?:\/\/[^\s<>"')]+)(?=[\s<>"')]|$)/gi;
const RB_RE = /\b(RB-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\b/g;

function isLikelyCommand(line: string): boolean {
  const t = line.trim();
  if (!t) return false;
  if (t.startsWith("$") || t.startsWith("#!")) return true;
  const lower = t.toLowerCase();
  const starters = [
    "kubectl ",
    "docker ",
    "aws ",
    "curl ",
    "helm ",
    "terraform ",
    "gcloud ",
    "az ",
    "psql ",
    "mysql ",
    "redis-cli ",
    "dig ",
    "openssl ",
    "ssh ",
    "jq ",
    "grep ",
    "journalctl ",
  ];
  return starters.some((s) => lower.startsWith(s));
}

function linkifySegment(
  segment: string,
  runbookBase: string | null,
  keyPrefix: string,
): ReactNode {
  const out: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  const re = new RegExp(RB_RE.source, RB_RE.flags);
  while ((m = re.exec(segment)) !== null) {
    if (m.index > last) {
      out.push(
        <Fragment key={`${keyPrefix}-t-${last}`}>
          {linkifyUrls(segment.slice(last, m.index), `${keyPrefix}-u-${last}`)}
        </Fragment>,
      );
    }
    const id = m[1];
    if (runbookBase) {
      const href = `${runbookBase}/${id}.md`;
      out.push(
        <a
          key={`${keyPrefix}-rb-${m.index}`}
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="font-mono text-violet-600 underline decoration-violet-400/60 underline-offset-2 hover:text-violet-500 dark:text-violet-400"
        >
          {id}
        </a>,
      );
    } else {
      out.push(
        <code
          key={`${keyPrefix}-rb-${m.index}`}
          className="rounded bg-violet-500/10 px-1 font-mono text-xs text-violet-800 dark:text-violet-200"
        >
          {id}
        </code>,
      );
    }
    last = m.index + m[0].length;
  }
  if (last < segment.length) {
    out.push(
      <Fragment key={`${keyPrefix}-end`}>
        {linkifyUrls(segment.slice(last), `${keyPrefix}-u-end`)}
      </Fragment>,
    );
  }
  if (!out.length) return linkifyUrls(segment, keyPrefix);
  return <>{out}</>;
}

function linkifyUrls(text: string, keyPrefix: string): ReactNode {
  const parts: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  const re = new RegExp(URL_RE.source, URL_RE.flags);
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) {
      parts.push(text.slice(last, m.index));
    }
    const href = m[1];
    parts.push(
      <a
        key={`${keyPrefix}-${m.index}`}
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="break-all text-violet-600 underline decoration-violet-400/60 underline-offset-2 hover:text-violet-500 dark:text-violet-400"
      >
        {href}
      </a>,
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) {
    parts.push(text.slice(last));
  }
  return parts.length ? <>{parts}</> : text;
}

function ActionLine({
  text,
  index,
  runbookBase,
}: {
  text: string;
  index: number;
  runbookBase: string | null;
}) {
  if (isLikelyCommand(text)) {
    return (
      <pre className="mt-1 overflow-x-auto rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2.5 font-mono text-xs leading-relaxed text-zinc-100 shadow-inner dark:border-zinc-600 dark:bg-black/40">
        {text.trim()}
      </pre>
    );
  }

  return (
    <div className="mt-1 text-sm leading-relaxed text-zinc-800 dark:text-zinc-200">
      {linkifySegment(text, runbookBase, `a-${index}`)}
    </div>
  );
}

type Props = {
  actions: string[];
};

/**
 * Renders actions with operator-friendly styling: shell-like lines as code blocks,
 * https:// links clickable, RB-* runbook ids linked when NEXT_PUBLIC_RUNBOOK_DOCS_BASE is set.
 */
export function OperationalActionsList({ actions }: Props) {
  const runbookBase = runbookDocsBaseUrl();
  return (
    <ol className="mt-2 list-decimal space-y-4 ps-5">
      {actions.map((a, i) => (
        <li key={i} className="marker:font-semibold marker:text-zinc-500">
          <ActionLine text={a} index={i} runbookBase={runbookBase} />
        </li>
      ))}
    </ol>
  );
}
