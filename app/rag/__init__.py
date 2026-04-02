"""Local RAG: load corpus, chunk, embed, FAISS index, retrieve."""

from app.rag.retrieve import retrieve

__all__ = ["retrieve"]
