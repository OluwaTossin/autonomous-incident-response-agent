# Version 3 Hosted FAISS Bundles

V3.9 defines the immutable artifact contract between hosted index construction and retrieval.
It does not provision AWS resources or introduce asynchronous jobs. Version 2 continues to use
its existing filesystem bundle and commands.

## Artifact Layout

Each index version owns one generated prefix:

```text
knowledge-indexes/<organization-id>/<workspace-id>/<index-version-id>/
  index.faiss
  chunks.jsonl
  manifest.json
```

User-controlled names do not form object keys. `index.faiss` and `chunks.jsonl` are written
first; `manifest.json` is the completion marker and is written last. Every put is immutable.
An existing identical object makes a retry idempotent; different bytes at the same key fail
closed.

## Manifest Schema 1

The canonical JSON manifest records:

- schema and bundle format versions;
- index, organization, and workspace identity;
- creation timestamp;
- embedding model and dimension;
- cosine-through-L2-normalized-inner-product similarity semantics;
- character-window chunking algorithm, version, size, and overlap;
- chunk count and tenant/system source provenance;
- byte size and lowercase SHA-256 checksum for `index.faiss` and `chunks.jsonl`.

The manifest contains no credentials, presigned URLs, customer content, object-store secrets,
or local cache paths. Unsupported schema or format versions fail closed.

## Build And Publication

An authorized `KNOWLEDGE_MANAGE` context selects the latest eligible verified document
versions under PostgreSQL RLS. The content reader revalidates tenant identity, availability,
content-safety state, deletion state, size, and checksum before returning bytes. An explicit
system corpus is disabled by default.

The builder uses a generated process-local temporary directory, existing character chunking,
the configured embedding model, normalized vectors, and `IndexFlatIP`. It records chunk-level
source provenance, builds the three-file bundle, and removes temporary files on success or
failure.

Publication uploads both data files and then the manifest. Read-back verification validates
the manifest checksum and identity plus every file's size and SHA-256. Only after this succeeds
does PostgreSQL move the index from `BUILDING` to `READY`.

## State And Activation

The lifecycle is:

```text
BUILDING -> READY -> ACTIVE -> INACTIVE
    |                            |
    +----------> FAILED          +-> ACTIVE (explicit rollback)
```

`READY`, `ACTIVE`, and `INACTIVE` require immutable publication metadata. Only `READY` can be
activated initially. Activation locks the workspace-visible index rows in a PostgreSQL
transaction, marks the previous `ACTIVE` version `INACTIVE`, activates the candidate, and
writes audit events before commit. The unique partial index still permits only one active
version per workspace. A failed transaction rolls back the supersession, leaving the previous
active version intact.

Rollback verifies the old immutable artifact before atomically activating an `INACTIVE`
version. It does not rebuild or mutate that artifact. Superseded bundles remain durable.

## Runtime Resolution And Cache

Runtime resolution performs fresh `KNOWLEDGE_READ` authorization, resolves the active
publication under RLS, and verifies the durable artifact. Integrity failures fail closed and
produce a durable audit event. `LocalFaissRetriever` receives only a verified local handle and
remains unaware of authorization, PostgreSQL, S3, and object keys.

The local cache key is the immutable index-version ID. On a miss it downloads into a hidden
generated directory, verifies manifest identity/schema, file sizes/checksums, and FAISS
dimension/chunk count, then atomically renames the directory into place. Corrupt entries are
removed and fetched again. File locks serialize a cold download and remain held in shared mode
while retrieval uses an entry, preventing eviction during reads.

Cache limits are configurable by entry count and bytes. Eviction selects the least recently
accessed directory by modification time, skips the current key, and skips locked entries. A
single artifact larger than the byte limit is rejected. A workspace activation naturally
changes the immutable key; cached historical versions need no invalidation and can make
rollback warm.

## Failure Recovery

- Partial upload never creates `READY` or replaces the active version; the index becomes
  `FAILED` and publication failure is audited.
- Missing objects, size/checksum mismatches, wrong identity, unsupported manifests, and corrupt
  FAISS data are never exposed to retrieval.
- Duplicate publication is safe only when existing bytes match exactly.
- Concurrent activation is serialized by row locks and the one-active unique index.
- Obviously incomplete local temporary directories are removed by the cache operation.
- Published inactive artifacts are retained. Orphan cleanup and durable retention/garbage
  collection are deferred to V3.25.

Build, publication, activation, rollback, supersession, and failed verification have durable
audit events. Injected observability hooks report build, publish, download, verification,
activation, cache hit/miss, and eviction outcomes with durations and no high-cardinality metric
dimensions. Hosted infrastructure will bind those hooks in later phases.

## Version 2 Compatibility

Version 2 still reads and writes loose `index.faiss`, `chunks.jsonl`, and `meta.json` in its
filesystem workspace. Its `rag-build`, `rag-query`, triage, FastAPI, Gradio, ranking, score,
evidence, and demo/user corpus behavior do not pass through hosted storage or cache.

V3.10 adds the transport-neutral durable job and representative index-build handler documented
in [`jobs.md`](jobs.md). V3.11 will add queues and worker composition around that contract. No
SQS, background loop, or deployed AWS resource is part of V3.9 or V3.10.
