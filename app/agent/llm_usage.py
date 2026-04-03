"""Aggregate LangChain ``UsageMetadataCallbackHandler`` totals for observability."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain_core.callbacks import UsageMetadataCallbackHandler


def aggregate_llm_usage(handler: UsageMetadataCallbackHandler) -> dict[str, Any]:
    """Sum input/output/total tokens across models invoked in the graph (typically one chat call)."""
    inp = out = 0
    for meta in handler.usage_metadata.values():
        d: dict[str, Any] = dict(meta) if isinstance(meta, Mapping) else {}
        inp += int(d.get("input_tokens") or 0)
        out += int(d.get("output_tokens") or 0)
    total = inp + out
    return {
        "tokens_prompt": inp,
        "tokens_completion": out,
        "tokens_total": total,
    }
