"""FAISS index persistence and chunk metadata."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import faiss
import numpy as np

from app.rag.chunking import TextChunk
from app.rag.config import rag_index_dir


def index_paths(base: Path | None = None) -> tuple[Path, Path, Path]:
    base = base or rag_index_dir()
    base.mkdir(parents=True, exist_ok=True)
    return base / "index.faiss", base / "chunks.jsonl", base / "meta.json"


def build_index(vectors: np.ndarray) -> faiss.Index:
    dim = vectors.shape[1]
    index = faiss.IndexFlatIP(dim)
    x = np.ascontiguousarray(vectors.astype("float32"))
    index.add(x)
    return index


def save_index(
    index: faiss.Index,
    chunks: list[TextChunk],
    *,
    embedding_model: str,
    base: Path | None = None,
) -> None:
    faiss_path, chunks_path, meta_path = index_paths(base)
    faiss.write_index(index, str(faiss_path))
    with chunks_path.open("w", encoding="utf-8") as f:
        for c in chunks:
            row = {key: value for key, value in asdict(c).items() if value is not None}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    meta = {
        "embedding_model": embedding_model,
        "dim": index.d,
        "num_chunks": len(chunks),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def load_index_bundle(base: Path | None = None) -> tuple[faiss.Index, list[TextChunk], dict]:
    faiss_path, chunks_path, meta_path = index_paths(base)
    if not faiss_path.is_file():
        raise FileNotFoundError(
            f"No index at {faiss_path}. Run: python -m app.rag.cli build-index"
        )
    index = faiss.read_index(str(faiss_path))
    chunks: list[TextChunk] = []
    with chunks_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            chunks.append(
                TextChunk(
                    text=d["text"],
                    source=d["source"],
                    doc_type=d["doc_type"],
                    chunk_index=int(d["chunk_index"]),
                    origin=d.get("origin"),
                    organization_id=d.get("organization_id"),
                    workspace_id=d.get("workspace_id"),
                    document_id=d.get("document_id"),
                    document_version_id=d.get("document_version_id"),
                    knowledge_index_version_id=d.get("knowledge_index_version_id"),
                )
            )
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return index, chunks, meta
