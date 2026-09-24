"""Top-k retrieval over the FAISS index."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.knowledge.contracts import (
    KnowledgeIndexHandle,
    KnowledgeSourceOrigin,
    LocalFaissIndexHandle,
)
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
    origin: KnowledgeSourceOrigin | None = None
    organization_id: str | None = None
    workspace_id: str | None = None
    document_id: str | None = None
    document_version_id: str | None = None
    knowledge_index_version_id: str | None = None


class LocalFaissRetriever:
    """Version 2 filesystem adapter preserving the existing FAISS semantics."""

    def retrieve(
        self,
        index: KnowledgeIndexHandle,
        query: str,
        *,
        top_k: int,
    ) -> list[RetrievalHit]:
        if not isinstance(index, LocalFaissIndexHandle):
            raise TypeError("LocalFaissRetriever requires a LocalFaissIndexHandle")
        faiss_index, chunks, _meta = load_index_bundle(index.index_dir)
        q = embed_texts([query])
        q = np.ascontiguousarray(q.astype("float32"))
        scores, indices = faiss_index.search(q, min(top_k, len(chunks)))
        hits: list[RetrievalHit] = []
        for score, idx in zip(scores[0], indices[0], strict=True):
            if idx < 0:
                continue
            chunk = chunks[idx]
            hits.append(
                RetrievalHit(
                    score=float(score),
                    text=chunk.text,
                    source=chunk.source,
                    doc_type=chunk.doc_type,
                    chunk_index=chunk.chunk_index,
                )
            )
        return hits


def retrieve(
    query: str,
    *,
    top_k: int = 5,
    index_dir=None,
) -> list[RetrievalHit]:
    resolved = Path(index_dir) if index_dir is not None else rag_index_dir()
    return LocalFaissRetriever().retrieve(
        LocalFaissIndexHandle(resolved), query, top_k=top_k
    )
