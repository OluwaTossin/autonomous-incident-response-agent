# Version 3 Knowledge And Retrieval Boundary

V3.8 separates how AIRA addresses knowledge from how a runtime stores and delivers index
artifacts. It preserves the Version 2 FAISS behavior while making hosted workspace authority
explicit. V3.8 does not build, publish, download, or cache hosted FAISS bundles.

## Contracts

The shared retrieval boundary has three narrow concepts:

- `KnowledgeSourceReference` describes an attributable tenant, system, or self-hosted source.
  Hosted tenant sources include organization, workspace, document, and document-version
  identity plus verified checksum, size, and media type. They never expose an object key.
- `LocalFaissIndexHandle` identifies the existing Version 2 filesystem bundle.
  `HostedKnowledgeIndexReference` identifies an authorized workspace index version and its
  source document versions, without an S3 key or local cache path.
- `Retriever` accepts an explicit index handle, query, and `top_k`, then returns the existing
  retrieval-hit shape. It does not authorize tenants or manage object storage and index
  lifecycle.

`RetrievalContext` injects the index, retriever, and retrieval parameters into the existing
LangGraph retrieval node. The shared triage pipeline does not know about PostgreSQL, S3, or
runtime mode flags.

## Hosted Resolution

The hosted flow is:

```text
ActorContext
  -> AuthorizationService
  -> sealed AuthorizedTenantContext
  -> PostgreSQL active-index/source resolver under transaction-local RLS
  -> HostedKnowledgeIndexReference
  -> Retriever supplied by hosted composition in V3.9
```

`HostedKnowledgeService` performs fresh `KNOWLEDGE_READ` authorization to resolve an active
index and fresh `KNOWLEDGE_MANAGE` authorization to select index inputs. Its repository port
accepts only `AuthorizedTenantContext`. The PostgreSQL adapter also checks the expected
permission and requires a workspace scope before applying RLS context. Returned scopes are
validated again at the application boundary.

The existing `knowledge_index_versions` table and one-active-index-per-workspace constraint
are sufficient for V3.8, so no migration is required. An active reference contains the index
version ID and linked document-version IDs. Artifact format manifests and locations remain a
V3.9 concern.

## Hosted Source Eligibility

Hosted index inputs are selected only from the authorized workspace. An eligible source is:

- a non-archived `AVAILABLE` document;
- in `runbook`, `incident`, `log`, or `knowledge` category;
- an `AVAILABLE` document version with verified checksum, size, and media type;
- not rejected by the recorded content-safety state; and
- the latest eligible available version of its logical document.

A newer pending or failed version does not displace the last verified available version.
Pending uploads, failed versions, archived documents, unsupported `other` documents, and
rejected versions are excluded. The selector returns metadata only; V3.9 will securely stage
the corresponding bytes for index construction.

## System Corpus Policy

Hosted system content is disabled by default. Enabling it requires an explicit
`SystemCorpusPolicy` containing explicit system source IDs and `system` provenance. Repository
decision documents are never silently merged into every tenant corpus. The Version 2 loader
continues its existing decision-document behavior for self-hosted compatibility.

## Provenance

The base retrieval hit fields remain `score`, `text`, `source`, `doc_type`, and `chunk_index`.
Hosted hits may additionally carry origin, organization/workspace IDs, document/version IDs,
and knowledge-index-version ID. Programmatic evidence and JSONL audit source summaries retain
those fields when present. Version 2 output remains unchanged when they are absent. Storage
keys, presigned URLs, document contents, and credentials are not provenance fields.

## Version 2 Compatibility

`LocalFaissRetriever` loads the existing `index.faiss`, `chunks.jsonl`, and `meta.json` bundle
and preserves the current embedding, inner-product search, ordering, scoring, `top_k`, source,
and chunk behavior. The existing `retrieve()` function remains the compatibility wrapper that
resolves `rag_index_dir()` only in self-hosted execution. `rag-build`, `rag-query`, CLI triage,
FastAPI `/triage`, Gradio, demo/user corpus modes, and filesystem workspaces keep their current
composition.

## V3.9 Artifact Lifecycle

V3.9 implements immutable hosted bundle construction, publication, activation, verified
download, rollback, and worker-local caching without changing the V3.8 authority boundary.
`PublishedKnowledgeIndexReference` combines an authorized hosted index identity with its
immutable artifact prefix, manifest schema version, and manifest checksum. It contains no
presigned URL or local path. The complete format and operating model are defined in
[`knowledge-bundles.md`](knowledge-bundles.md).

Durable scheduling, retries, and worker orchestration remain deferred to V3.10 and V3.11.
Conservative retention means superseded published bundles are not automatically deleted;
durable retention and garbage-collection policy remains deferred to V3.25.
