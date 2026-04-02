"""Markdown report from evaluation rows."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def render_markdown(
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    *,
    gold_path: str,
) -> str:
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    lines: list[str] = [
        "# Triage evaluation report",
        "",
        f"- **Generated:** {now}",
        f"- **Gold file:** `{gold_path}`",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Cases | {summary['total']} |",
        f"| Passed | {summary['passed']} |",
        f"| Failed | {summary['failed']} |",
        f"| Pass rate | {summary['pass_rate']:.1%} |",
        f"| Mean latency (ms) | {summary['mean_latency_ms']} |",
        f"| p95 latency (ms) | {summary['p95_latency_ms']} |",
        "",
        "## Per case",
        "",
    ]

    for r in rows:
        cid = r.get("case_id", "?")
        ok = "✅ pass" if r.get("passed") else "❌ fail"
        lines.append(f"### `{cid}` — {ok}")
        ch = r.get("checks") or {}
        lines.append("")
        lines.append("| Check | Value |")
        lines.append("|-------|-------|")
        for k, v in sorted(ch.items()):
            if k == "case_id":
                continue
            lines.append(f"| `{k}` | {v} |")
        lines.append("")
        if r.get("failures"):
            lines.append("**Failures:**")
            for f in r["failures"]:
                lines.append(f"- {f}")
            lines.append("")

    lines.extend(
        [
            "## Notes",
            "",
            "- **Classification** uses gold `expect` fields; tune `severity_any_of` if your model is calibrated differently.",
            "- **Retrieval** checks are substring-based on hit `source` paths.",
            "- **Evidence grounding** is a cheap overlap heuristic vs retrieval hits (not a full hallucination judge).",
            "",
        ]
    )
    return "\n".join(lines)
