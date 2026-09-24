"""Tenant-explicit knowledge contracts and hosted resolution services."""

from app.knowledge.contracts import (
    HostedKnowledgeIndexReference,
    KnowledgeSourceReference,
    LocalFaissIndexHandle,
    RetrievalContext,
    Retriever,
)

__all__ = [
    "HostedKnowledgeIndexReference",
    "KnowledgeSourceReference",
    "LocalFaissIndexHandle",
    "RetrievalContext",
    "Retriever",
]
