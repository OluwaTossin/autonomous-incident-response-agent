"""Compare triage output + retrieval meta to gold expectations."""

from __future__ import annotations

from typing import Any

from app.eval.schema import GoldExpect


def _norm_sev(s: str) -> str:
    return str(s or "").strip().upper()


def evidence_grounding_ratio(result: dict[str, Any], hits: list[dict[str, Any]]) -> tuple[float, int, int]:
    """
    Fraction of evidence items whose ``source`` appears in retrieval hit sources or rag (cheap heuristic).

    Returns (ratio, grounded_count, total_evidence).
    """
    ev = result.get("evidence")
    if not isinstance(ev, list) or not ev:
        return 1.0, 0, 0
    hit_sources = [str(h.get("source") or "").lower() for h in hits if isinstance(h, dict)]
    blob = "|".join(hit_sources)
    grounded = 0
    for item in ev:
        if not isinstance(item, dict):
            continue
        src = str(item.get("source") or "").lower()
        if not src:
            continue
        if any(src in hs or hs in src for hs in hit_sources if hs):
            grounded += 1
        elif src and src in blob:
            grounded += 1
    total = len([x for x in ev if isinstance(x, dict) and str(x.get("source") or "").strip()])
    if total == 0:
        return 1.0, 0, 0
    return grounded / total, grounded, total


def evaluate_case(
    case_id: str,
    result: dict[str, Any],
    meta: dict[str, Any],
    expect: GoldExpect,
    *,
    latency_ms: float,
) -> dict[str, Any]:
    """Return structured pass/fail + human-readable failure lines."""
    failures: list[str] = []
    checks: dict[str, Any] = {"case_id": case_id, "latency_ms": round(latency_ms, 2)}

    if result.get("error"):
        failures.append(f"graph_error: {result.get('error')}")
        checks["severity_ok"] = False
        hits = meta.get("retrieval_hits") if isinstance(meta.get("retrieval_hits"), list) else []
        ratio, g, t = evidence_grounding_ratio(result, hits)
        checks["evidence_grounded_ratio"] = ratio
        checks["evidence_grounded"] = f"{g}/{t}"
        return {"passed": False, "failures": failures, "checks": checks}

    sev = _norm_sev(str(result.get("severity", "")))
    if expect.severity is not None:
        ok = sev == _norm_sev(expect.severity)
        checks["severity_ok"] = ok
        if not ok:
            failures.append(f"severity: expected {expect.severity!r}, got {result.get('severity')!r}")
    elif expect.severity_any_of:
        allowed = {_norm_sev(x) for x in expect.severity_any_of}
        ok = sev in allowed
        checks["severity_ok"] = ok
        if not ok:
            failures.append(f"severity: expected one of {expect.severity_any_of}, got {result.get('severity')!r}")
    else:
        checks["severity_ok"] = None

    if expect.escalate is not None:
        actual = bool(result.get("escalate"))
        ok = actual == expect.escalate
        checks["escalate_ok"] = ok
        if not ok:
            failures.append(f"escalate: expected {expect.escalate}, got {actual}")
    else:
        checks["escalate_ok"] = None

    actions = result.get("recommended_actions")
    n_act = len(actions) if isinstance(actions, list) else 0
    if expect.min_actions is not None:
        ok = n_act >= expect.min_actions
        checks["min_actions_ok"] = ok
        checks["action_count"] = n_act
        if not ok:
            failures.append(f"actions: need >= {expect.min_actions}, got {n_act}")
    else:
        checks["min_actions_ok"] = None

    summary = str(result.get("incident_summary") or "").lower()
    if expect.summary_contains_all:
        missing = [k for k in expect.summary_contains_all if k.lower() not in summary]
        ok = not missing
        checks["summary_keywords_ok"] = ok
        if not ok:
            failures.append(f"summary missing keywords: {missing}")
    else:
        checks["summary_keywords_ok"] = None

    rc = str(result.get("likely_root_cause") or "").lower()
    if expect.root_cause_contains_any:
        ok = any(k.lower() in rc for k in expect.root_cause_contains_any)
        checks["root_cause_hint_ok"] = ok
        if not ok:
            failures.append("root_cause: none of expected phrases found")
    else:
        checks["root_cause_hint_ok"] = None

    hits = meta.get("retrieval_hits") if isinstance(meta.get("retrieval_hits"), list) else []
    hit_sources = [str(h.get("source") or "") for h in hits if isinstance(h, dict)]
    scores = []
    for h in hits:
        if isinstance(h, dict):
            try:
                scores.append(float(h.get("score", 0.0)))
            except (TypeError, ValueError):
                scores.append(0.0)
    top_score = max(scores) if scores else 0.0
    checks["top_retrieval_score"] = round(top_score, 4)

    if expect.min_top_retrieval_score is not None:
        ok = top_score >= expect.min_top_retrieval_score
        checks["min_top_score_ok"] = ok
        if not ok:
            failures.append(
                f"retrieval score: max {top_score:.4f} < required {expect.min_top_retrieval_score}"
            )
    else:
        checks["min_top_score_ok"] = None

    if expect.retrieval_source_contains_any:
        needles = [n.lower() for n in expect.retrieval_source_contains_any]
        hay = " ".join(hit_sources).lower()
        ok = any(n in hay for n in needles)
        checks["retrieval_source_ok"] = ok
        if not ok:
            failures.append(f"retrieval: no hit source contained any of {expect.retrieval_source_contains_any}")
    else:
        checks["retrieval_source_ok"] = None

    ratio, g, t = evidence_grounding_ratio(result, hits)
    checks["evidence_grounded_ratio"] = round(ratio, 4)
    checks["evidence_grounded"] = f"{g}/{t}"

    passed = len(failures) == 0
    return {"passed": passed, "failures": failures, "checks": checks}
