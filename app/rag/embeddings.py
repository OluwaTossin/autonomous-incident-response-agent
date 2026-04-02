"""OpenAI-compatible embedding client."""

from __future__ import annotations

import numpy as np
from openai import OpenAI

from app.rag.config import embedding_model, openai_api_key, openai_base_url


def get_client() -> OpenAI:
    kwargs: dict = {"api_key": openai_api_key()}
    base = openai_base_url()
    if base:
        kwargs["base_url"] = base
    return OpenAI(**kwargs)


def embed_texts(
    texts: list[str],
    batch_size: int = 64,
    model: str | None = None,
) -> np.ndarray:
    """Return float32 matrix (n, dim), L2-normalized rows for cosine / inner product."""
    client = get_client()
    model = model or embedding_model()
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = client.embeddings.create(model=model, input=batch)
        # API returns in request order
        by_index = sorted(resp.data, key=lambda d: d.index)
        vectors.extend([d.embedding for d in by_index])
    arr = np.array(vectors, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    arr = arr / norms
    return arr
