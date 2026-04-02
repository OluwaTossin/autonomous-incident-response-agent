"""CLI: run triage from JSON file or stdin."""

from __future__ import annotations

import argparse
import json
import sys
from uuid import uuid4

from app.agent.graph import run_triage


def main(args: list[str] | None = None) -> int:
    if args is None:
        args = sys.argv[1:]
    p = argparse.ArgumentParser(description="LangGraph incident triage (Phase 4)")
    p.add_argument(
        "--file",
        "-f",
        type=str,
        default="",
        help="Path to JSON incident payload",
    )
    p.add_argument(
        "--stdin",
        action="store_true",
        help="Read JSON incident from stdin",
    )
    ns = p.parse_args(args)

    if ns.stdin:
        raw = sys.stdin.read()
    elif ns.file:
        from pathlib import Path

        raw = Path(ns.file).read_text(encoding="utf-8")
    else:
        p.error("Provide --file path.json or --stdin")

    try:
        incident = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}", file=sys.stderr)
        return 1

    if not isinstance(incident, dict):
        print("JSON root must be an object", file=sys.stderr)
        return 1

    result = {**run_triage(incident), "triage_id": str(uuid4())}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if "error" not in result or not result.get("error") else 2


if __name__ == "__main__":
    raise SystemExit(main(None))
