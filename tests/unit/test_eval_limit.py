"""Gold suite limit (CI smoke)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from app.eval.runner import run_suite


def test_run_suite_respects_limit(tmp_path: Path) -> None:
    gold = tmp_path / "g.jsonl"
    lines = [
        json.dumps(
            {
                "id": f"c{j}",
                "incident": {"title": "t", "description": "d", "source": "s"},
                "expect": {},
            }
        )
        for j in range(5)
    ]
    gold.write_text("\n".join(lines), encoding="utf-8")

    with patch("app.eval.runner.run_triage_with_audit") as m:
        m.return_value = (
            {
                "incident_summary": "s",
                "severity": "LOW",
                "escalate": False,
                "recommended_actions": ["a"],
                "likely_root_cause": "x",
            },
            {"rag_context": "", "retrieval_hits": [], "llm_usage": {}},
        )
        rows = run_suite(gold, disable_audit=True, limit=2)

    assert len(rows) == 2
    assert m.call_count == 2
