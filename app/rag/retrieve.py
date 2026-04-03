"""Top-k retrieval over the FAISS index."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.rag.config import rag_index_dir
from app.rag.embeddings import embed_texts
from app.rag.index_store import load_index_bundle


@dataclass
class RetrievalHit:
    score: float
    text: str
    source: str
    doc_type: str
    chunk_index: int


def retrieve(
    query: str,
    *,
    top_k: int = 5,
    index_dir=None,
) -> list[RetrievalHit]:
    index_dir = index_dir or rag_index_dir()
    index, chunks, _meta = load_index_bundle(index_dir)
    q = embed_texts([query])
    q = np.ascontiguousarray(q.astype("float32"))
    scores, indices = index.search(q, min(top_k, len(chunks)))
    hits: list[RetrievalHit] = []
    for score, idx in zip(scores[0], indices[0], strict=True):
        if idx < 0:
            continue
        c = chunks[idx]
        hits.append(
            RetrievalHit(
                score=float(score),
                text=c.text,
                source=c.source,
                doc_type=c.doc_type,
                chunk_index=c.chunk_index,
            )
        )
    return hits
