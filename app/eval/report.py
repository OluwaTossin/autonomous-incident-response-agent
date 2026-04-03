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
        "| Metric | Value |",
        "|--------|-------|",
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
        if r.get("tags"):
            lines.append(f"*Tags:* `{', '.join(r['tags'])}`")
        if r.get("notes"):
            lines.append(f"*Notes:* {r['notes']}")
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
            "- **`None` in a check** means that assertion was not requested for that row (add `summary_contains_all`, `root_cause_contains_any`, `retrieval_source_contains_any`, etc. in `expect` to enforce).",
            "- **Retrieval** checks are substring-based on hit `source` paths; requires a built index for meaningful scores.",
            "- **Evidence grounding** is a cheap overlap heuristic vs retrieval hits (not a full hallucination judge).",
            "- **Tags** (`ambiguous`, `misleading_alert`, …) are documentation for humans; they do not change pass/fail logic.",
            "",
        ]
    )
    return "\n".join(lines)
