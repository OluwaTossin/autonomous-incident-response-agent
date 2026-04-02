"""Unit tests for deterministic triage signal reasoning."""

from __future__ import annotations

from app.agent.signal_reasoning import (
    active_signal_tags,
    build_programmatic_timeline,
    detect_conflicting_signals,
    evidence_from_retrieval_dicts,
    merge_evidence_lists,
    merge_timelines,
)


def test_evidence_merges_chunks_per_source():
    hits = [
        {"score": 0.9, "source": "data/runbooks/rb.md", "doc_type": "runbook"},
        {"score": 0.85, "source": "data/runbooks/rb.md", "doc_type": "runbook"},
        {"score": 0.7, "source": "data/incidents/x.md", "doc_type": "incident"},
    ]
    ev = evidence_from_retrieval_dicts(hits)
    assert len(ev) == 2
    rb = next(e for e in ev if "rb.md" in e["source"])
    assert rb["type"] == "runbook"
    assert "2 chunks" in rb["reason"]


def test_merge_evidence_programmatic_wins_duplicate_source():
    prog = [{"type": "runbook", "source": "data/a.md", "reason": "Retrieved x"}]
    llm = [{"type": "runbook", "source": "data/a.md", "reason": "LLM duplicate"}]
    merged = merge_evidence_lists(prog, llm)
    assert len(merged) == 1
    assert merged[0]["reason"] == "Retrieved x"


def test_merge_evidence_appends_distinct_llm_row():
    prog = [{"type": "runbook", "source": "data/a.md", "reason": "R"}]
    llm = [{"type": "metric", "source": "metric_summary", "reason": "CPU 94% in payload"}]
    merged = merge_evidence_lists(prog, llm)
    assert len(merged) == 2
    assert merged[1]["type"] == "metric"


def test_detect_conflicting_signals_cpu_and_db():
    incident = {
        "alert_title": "payment errors",
        "metric_summary": "High CPU 94% and connection pool exhausted on RDS",
        "logs": "",
    }
    msg = detect_conflicting_signals(incident)
    assert msg is not None
    assert "Conflicting signals" in msg
    assert "cpu" in msg.lower() or "compute" in msg.lower()
    tags = active_signal_tags(incident)
    assert "cpu" in tags and "db_conn" in tags


def test_detect_conflicting_signals_single_family():
    incident = {"metric_summary": "CPU at 99%", "logs": "", "alert_title": "cpu"}
    assert detect_conflicting_signals(incident) is None


def test_build_programmatic_timeline_anchor_and_iso():
    incident = {
        "time_of_occurrence": "2026-04-10T14:05:00Z",
        "logs": "spike at 2026-04-10T14:06:00Z then errors",
        "metric_summary": "",
    }
    tl = build_programmatic_timeline(incident)
    assert any("reference time" in x for x in tl)
    assert any("2026-04-10T14:06:00Z" in x for x in tl)


def test_merge_timelines_dedupes():
    a = ["Condition / alert reference time: T0", "foo"]
    b = ["foo", "bar"]
    m = merge_timelines(a, b)
    assert m == ["Condition / alert reference time: T0", "foo", "bar"]
