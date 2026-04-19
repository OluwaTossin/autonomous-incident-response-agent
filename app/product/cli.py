"""Product CLIs: workspace validation and workspace-scoped index build."""

from __future__ import annotations

import argparse
import os
import sys

from app.config import reset_settings
from app.product.workspace_layout import validate_workspace_layout
from app.rag.cli import main as rag_main


def _apply_workspace_env(workspace: str) -> None:
    w = (workspace or "default").strip() or "default"
    os.environ["WORKSPACE_ID"] = w


def _restore_env(key: str, previous: str | None) -> None:
    if previous is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = previous


def main_validate_workspace(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(prog="product-validate-workspace", description="Check workspace layout under data/.")
    p.add_argument("--workspace", "-w", default=os.environ.get("WORKSPACE_ID", "default"))
    p.add_argument("--strict", action="store_true", help="Fail if no indexed corpus files under workspace data/.")
    args = p.parse_args(argv)

    prev_ws = os.environ.get("WORKSPACE_ID")
    try:
        _apply_workspace_env(args.workspace)
        reset_settings()

        errs, warns = validate_workspace_layout(require_corpus_files=args.strict)
        for line in warns:
            print(f"warning: {line}", file=sys.stderr)
        for line in errs:
            print(f"error: {line}", file=sys.stderr)
        if errs:
            return 1
        print("Workspace layout OK.")
        return 0
    finally:
        _restore_env("WORKSPACE_ID", prev_ws)
        reset_settings()


def main_build_index(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    p = argparse.ArgumentParser(
        prog="product-build-index",
        description="Validate workspace, then build FAISS index (workspace corpus + repo decisions).",
    )
    p.add_argument("--workspace", "-w", default=os.environ.get("WORKSPACE_ID", "default"))
    p.add_argument("--dry-run", action="store_true", help="Validate only; do not write index.")
    p.add_argument("--strict", action="store_true", help="Fail validation if workspace data/ has no corpus files.")
    args, remainder = p.parse_known_args(argv)

    prev_ws = os.environ.get("WORKSPACE_ID")
    prev_wo = os.environ.get("RAG_WORKSPACE_ONLY")
    try:
        _apply_workspace_env(args.workspace)
        os.environ["RAG_WORKSPACE_ONLY"] = "1"
        reset_settings()

        errs, warns = validate_workspace_layout(require_corpus_files=args.strict)
        for line in warns:
            print(f"warning: {line}", file=sys.stderr)
        for line in errs:
            print(f"error: {line}", file=sys.stderr)
        if errs:
            return 1
        if args.dry_run:
            print("Dry run: validation passed; skipping index build.")
            return 0

        return rag_main(["build-index", *remainder])
    finally:
        _restore_env("WORKSPACE_ID", prev_ws)
        _restore_env("RAG_WORKSPACE_ONLY", prev_wo)
        reset_settings()


def cli_validate() -> None:
    raise SystemExit(main_validate_workspace())


def cli_build() -> None:
    raise SystemExit(main_build_index())
