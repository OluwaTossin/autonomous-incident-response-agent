"""Character-based chunking with overlap."""

from __future__ import annotations

from dataclasses import dataclass

from app.rag.loader import SourceDocument


@dataclass
class TextChunk:
    text: str
    source: str
    doc_type: str
    chunk_index: int
    origin: str | None = None
    organization_id: str | None = None
    workspace_id: str | None = None
    document_id: str | None = None
    document_version_id: str | None = None
    knowledge_index_version_id: str | None = None


def chunk_documents(
    documents: list[SourceDocument],
    chunk_size: int = 900,
    chunk_overlap: int = 150,
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    for doc in documents:
        text = doc.text
        if len(text) <= chunk_size:
            chunks.append(
                TextChunk(
                    text=text.strip(),
                    source=doc.source,
                    doc_type=doc.doc_type,
                    chunk_index=0,
                )
            )
            continue
        start = 0
        idx = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            piece = text[start:end].strip()
            if piece:
                chunks.append(
                    TextChunk(
                        text=piece,
                        source=doc.source,
                        doc_type=doc.doc_type,
                        chunk_index=idx,
                    )
                )
                idx += 1
            if end >= len(text):
                break
            start = end - chunk_overlap
            if start < 0:
                start = 0
            if start >= len(text):
                break
    return chunks
