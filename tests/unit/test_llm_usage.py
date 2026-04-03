"""LLM token aggregation for observability."""

from __future__ import annotations

from langchain_core.callbacks import UsageMetadataCallbackHandler

from app.agent.llm_usage import aggregate_llm_usage


def test_aggregate_llm_usage_sums_models() -> None:
    h = UsageMetadataCallbackHandler()
    h.usage_metadata = {
        "gpt-4o-mini": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
    }
    u = aggregate_llm_usage(h)
    assert u["tokens_prompt"] == 100
    assert u["tokens_completion"] == 50
    assert u["tokens_total"] == 150


def test_aggregate_llm_usage_empty() -> None:
    h = UsageMetadataCallbackHandler()
    u = aggregate_llm_usage(h)
    assert u["tokens_total"] == 0
