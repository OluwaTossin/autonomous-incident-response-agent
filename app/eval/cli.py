"""CLI: `uv run triage-eval` — run gold set, print or write Markdown report."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.eval.report import render_markdown
from app.eval.runner import aggregate, run_suite
from app.rag.config import project_root


def main(args: list[str] | None = None) -> int:
    root = project_root()
    default_gold = root / "data" / "eval" / "gold.jsonl"

    p = argparse.ArgumentParser(description="Run triage evaluation against a gold JSONL file")
    p.add_argument(
        "--gold",
        type=Path,
        default=default_gold,
        help=f"Path to gold JSONL (default: {default_gold})",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write Markdown report to this path (default: print to stdout)",
    )
    p.add_argument(
        "--keep-audit",
        action="store_true",
        help="Do not force TRIAGE_AUDIT_DISABLE (each run still appends audit lines if enabled)",
    )
    ns = p.parse_args(args=args)

    gold = ns.gold
    if not gold.is_file():
        print(f"Gold file not found: {gold}", file=sys.stderr)
        return 2

    rows = run_suite(gold, disable_audit=not ns.keep_audit)
    summ = aggregate(rows)
    md = render_markdown(rows, summ, gold_path=str(gold.resolve()))

    if ns.out:
        ns.out.parent.mkdir(parents=True, exist_ok=True)
        ns.out.write_text(md, encoding="utf-8")
        print(f"Wrote report: {ns.out}", file=sys.stderr)
    else:
        print(md)

    return 0 if summ["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
