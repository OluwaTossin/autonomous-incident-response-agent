"""Run gold cases through the triage graph and aggregate results."""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any, Iterator

from app.agent.graph import run_triage_with_audit
from app.eval.metrics import evaluate_case
from app.eval.schema import GoldCase


def iter_gold_cases(path: Path) -> Iterator[GoldCase]:
    text = path.read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {e}") from e
        yield GoldCase.model_validate(raw)


def run_suite(
    gold_path: Path,
    *,
    disable_audit: bool = True,
) -> list[dict[str, Any]]:
    """Run each gold case; return list of evaluate_case outputs + case id."""
    prev_audit = os.environ.get("TRIAGE_AUDIT_DISABLE")
    if disable_audit:
        os.environ["TRIAGE_AUDIT_DISABLE"] = "1"

    rows: list[dict[str, Any]] = []
    try:
        for case in iter_gold_cases(gold_path):
            t0 = time.perf_counter()
            result, meta = run_triage_with_audit(case.incident)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            ev = evaluate_case(case.id, result, meta, case.expect, latency_ms=elapsed_ms)
            ev["case_id"] = case.id
            if case.tags:
                ev["tags"] = case.tags
            if case.notes:
                ev["notes"] = case.notes
            rows.append(ev)
    finally:
        if disable_audit:
            if prev_audit is None:
                os.environ.pop("TRIAGE_AUDIT_DISABLE", None)
            else:
                os.environ["TRIAGE_AUDIT_DISABLE"] = prev_audit

    return rows


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    passed = sum(1 for r in rows if r.get("passed"))
    latencies = [r["checks"]["latency_ms"] for r in rows if "checks" in r]
    mean_lat = sum(latencies) / len(latencies) if latencies else 0.0
    sorted_lat = sorted(latencies)
    if sorted_lat:
        idx = min(len(sorted_lat) - 1, max(0, math.ceil(0.95 * len(sorted_lat)) - 1))
        p95 = sorted_lat[idx]
    else:
        p95 = 0.0
    return {
        "total": n,
        "passed": passed,
        "failed": n - passed,
        "pass_rate": round(passed / n, 4) if n else 0.0,
        "mean_latency_ms": round(mean_lat, 2),
        "p95_latency_ms": round(p95, 2),
    }
