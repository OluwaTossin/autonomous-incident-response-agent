"""FAISS compatibility and explicit retrieval-context tests."""

from __future__ import annotations

from importlib import import_module

import numpy as np
import pytest

from app.agent.nodes import node_retrieval
from app.agent.signal_reasoning import evidence_from_retrieval_dicts
from app.api.audit import top_k_sources_from_hits
from app.domain.common import WorkspaceScope
from app.domain.identifiers import (
    DocumentId,
    DocumentVersionId,
    KnowledgeIndexVersionId,
    OrganizationId,
    WorkspaceId,
)
from app.knowledge.contracts import (
    HostedKnowledgeIndexReference,
    KnowledgeSourceOrigin,
    LocalFaissIndexHandle,
    RetrievalContext,
)
from app.rag.chunking import TextChunk
from app.rag.index_store import build_index, save_index
from app.rag.retrieve import LocalFaissRetriever, RetrievalHit, retrieve


def _id(identifier_type, suffix: int):
    return identifier_type(f"00000000-0000-4000-8000-{suffix:012d}")


def test_local_adapter_preserves_v2_order_scores_sources_and_top_k(
    tmp_path, monkeypatch
) -> None:
    vectors = np.asarray([[1.0, 0.0], [0.0, 1.0], [0.8, 0.2]], dtype="float32")
    chunks = [
        TextChunk("first", "data/runbooks/first.md", "runbook", 0),
        TextChunk("second", "data/logs/second.log", "log", 0),
        TextChunk("third", "data/incidents/third.md", "incident", 2),
    ]
    save_index(build_index(vectors), chunks, embedding_model="fixture", base=tmp_path)
    retrieval_module = import_module("app.rag.retrieve")
    monkeypatch.setattr(
        retrieval_module,
        "embed_texts",
        lambda texts: np.asarray([[1.0, 0.0]], dtype="float32"),
    )

    compatible = retrieve("checkout", top_k=2, index_dir=tmp_path)
    explicit = LocalFaissRetriever().retrieve(
        LocalFaissIndexHandle(tmp_path), "checkout", top_k=2
    )

    assert explicit == compatible
    assert [hit.source for hit in explicit] == [
        "data/runbooks/first.md",
        "data/incidents/third.md",
    ]
    assert [hit.score for hit in explicit] == pytest.approx([1.0, 0.8])
    assert explicit[1].chunk_index == 2


class HostedRetriever:
    def __init__(self, hit: RetrievalHit) -> None:
        self.hit = hit
        self.calls = []

    def retrieve(self, index, query, *, top_k):
        self.calls.append((index, query, top_k))
        return [self.hit]


def test_explicit_hosted_context_flows_provenance_without_storage_details() -> None:
    organization_id = _id(OrganizationId, 10)
    workspace_id = _id(WorkspaceId, 11)
    index_id = _id(KnowledgeIndexVersionId, 12)
    document_id = _id(DocumentId, 13)
    version_id = _id(DocumentVersionId, 14)
    index = HostedKnowledgeIndexReference(
        WorkspaceScope(organization_id, workspace_id), index_id, (version_id,)
    )
    hit = RetrievalHit(
        0.91,
        "Scale workers.",
        "checkout.md",
        "runbook",
        3,
        origin=KnowledgeSourceOrigin.TENANT,
        organization_id=str(organization_id),
        workspace_id=str(workspace_id),
        document_id=str(document_id),
        document_version_id=str(version_id),
        knowledge_index_version_id=str(index_id),
    )
    retriever = HostedRetriever(hit)

    result = node_retrieval(
        {"retrieval_query": "checkout latency"},
        retrieval_context=RetrievalContext(index, retriever, 4),
    )

    assert retriever.calls == [(index, "checkout latency", 4)]
    state_hit = result["retrieval_hits"][0]
    assert state_hit["origin"] == "tenant"
    assert state_hit["document_version_id"] == str(version_id)
    assert state_hit["knowledge_index_version_id"] == str(index_id)
    assert "object_key" not in state_hit

    evidence = evidence_from_retrieval_dicts(result["retrieval_hits"])[0]
    assert evidence["document_id"] == str(document_id)
    assert evidence["chunk_index"] == 3
    assert evidence["score"] == 0.91
    audit_source = top_k_sources_from_hits(result["retrieval_hits"])[0]
    assert audit_source["workspace_id"] == str(workspace_id)
    assert "object_key" not in audit_source


def test_v2_evidence_shape_remains_unchanged_without_hosted_provenance() -> None:
    hit = {
        "score": 0.75,
        "source": "data/runbooks/checkout.md",
        "doc_type": "runbook",
        "chunk_index": 1,
    }

    assert evidence_from_retrieval_dicts([hit]) == [
        {
            "type": "runbook",
            "source": "data/runbooks/checkout.md",
            "reason": "Retrieved from knowledge index (similarity=0.750)",
        }
    ]


def test_hosted_evidence_does_not_merge_distinct_versions_with_same_filename() -> None:
    base = {
        "score": 0.75,
        "source": "checkout.md",
        "doc_type": "runbook",
        "chunk_index": 1,
        "origin": "tenant",
    }
    hits = [
        {**base, "document_version_id": "version-a"},
        {**base, "score": 0.7, "document_version_id": "version-b"},
    ]

    evidence = evidence_from_retrieval_dicts(hits)

    assert [item["document_version_id"] for item in evidence] == [
        "version-a",
        "version-b",
    ]
