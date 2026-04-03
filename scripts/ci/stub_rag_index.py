#!/usr/bin/env python3
"""Create a minimal `.rag_index` for Docker builds in CI (no OpenAI / embeddings).

Writes one chunk and a single normalized vector so `COPY .rag_index` in the Dockerfile succeeds.
Runtime retrieval quality is not the goal — only image build parity with production layout.
"""

from __future__ import annotations

import numpy as np

from app.rag.chunking import TextChunk
from app.rag.config import project_root
from app.rag.index_store import build_index, save_index

_EMBED_DIM = 1536
_EMBED_MODEL = "text-embedding-3-small"


def main() -> int:
    out = project_root() / ".rag_index"
    vec = np.zeros((1, _EMBED_DIM), dtype=np.float32)
    vec[0, 0] = 1.0
    index = build_index(vec)
    chunks = [
        TextChunk(
            text="ci-stub-chunk",
            source="scripts/ci/stub_rag_index.py",
            doc_type="knowledge",
            chunk_index=0,
        )
    ]
    save_index(index, chunks, embedding_model=_EMBED_MODEL, base=out)
    print(f"Wrote stub RAG index to {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
