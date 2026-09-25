# Version 3 Hosted Workspaces

V3.6 separates hosted workspace identity and configuration from the Version 2
process-selected filesystem workspace. Hosted services resolve a durable PostgreSQL
workspace for each operation; they never read `WORKSPACE_ID`, call filesystem path helpers,
or use a mutable global "current workspace".

## Two Workspace Models

| Concern | Version 2 self-hosted | Version 3 hosted |
|---|---|---|
| Selection | Process-wide `WORKSPACE_ID` | Authorized request/job scope |
| Identity | Filesystem directory name | Opaque `WorkspaceId` in PostgreSQL |
| Metadata | Directory/config files | Versioned workspace row |
| Configuration | YAML and environment precedence | Typed versioned database record |
| Data/index paths | `workspaces/<id>/data` and `index` | Not defined by V3.6 |
| Authorization | Shared deployment keys | V3.5 RBAC and workspace grants |
| Isolation | Trusted local deployment | Application authorization plus PostgreSQL RLS |

`app/workspace/paths.py`, `WORKSPACE_ID`, demo/user mode, operator overrides, local FAISS,
the product CLI, current FastAPI/Gradio behavior, and filesystem upload/reindex routes remain
the Version 2 composition. V3.6 does not redirect those paths to PostgreSQL.

## Lifecycle

`HostedWorkspaceService` supports:

- create with a generated opaque ID, organization-unique normalized slug, name, and
  optional description;
- retrieve an active authorized workspace;
- list active workspaces visible through current membership or machine grants;
- update name, slug, or description with an expected version;
- archive an active workspace with an expected version;
- read and update typed workspace configuration.

Names are not unique because teams may reasonably reuse display names. Slugs are unique
within an organization and use lowercase letters, digits, and hyphens. Archived workspaces
remain durable for dependent records and audit history but fail authorization for reads and
mutations. Restore is deliberately not included because dependent-resource restoration
semantics have not yet been defined.

Every service method starts from `ActorContext` and performs fresh authorization. Public
callers cannot provide `AuthorizedTenantContext`, and contexts are neither cached nor used
as session state. Workspace creation generates the ID inside the service and obtains a
creation-specific sealed context before opening its RLS transaction.

## Configuration Schema

Hosted workspace configuration schema version 1 contains only:

| Setting | Validation | Purpose |
|---|---|---|
| `rag_top_k` | Integer, 1 through 64 | Maximum retrieval results requested by hosted triage |
| `llm_temperature` | Number, 0 through 2 | Hosted triage generation temperature |

Unknown keys and empty patches fail validation. Therefore credentials and secret-like keys
such as API keys, tokens, provider secrets, or role credentials cannot be stored through
this contract. The database also enforces schema version, value ranges, tenant ownership,
and one configuration row per workspace.

The following remain deployment/global configuration:

- PostgreSQL and OIDC connection/provider settings;
- LLM provider credentials, API/admin keys, and service secrets;
- network binding, CORS, rate limits, upload limits, and telemetry settings;
- model and embedding-model allowlists/selections;
- filesystem roots, corpus paths, data mode, and self-hosted index paths.

Integration configuration is owned by V3.16, quotas by V3.24, and retention/deletion
controls by V3.25. Secret references belong with the later integration and security
design. They are not represented as arbitrary JSON placeholders in V3.6.

## Concurrency And Audit

Workspace metadata and configuration have independent positive integer versions. Updates
require the version observed by the caller and execute a SQL compare-and-swap:

```text
client A reads N
client B updates WHERE version = N -> N + 1
client A updates WHERE version = N -> conflict
```

No database lock spans user think-time. Workspace creation, metadata changes,
configuration changes, and archive write a durable audit event in the same transaction.
Events include actor, organization, workspace, action, target, timestamp, correlation, and
safe before/after values. Configuration rows also retain the latest updating actor and
timestamp; no secrets are present in configuration or audit details.

## Authorization And RLS

The hosted path is:

```text
ActorContext
  -> current V3.5 membership/service-account/system policy
  -> sealed AuthorizedTenantContext
  -> HostedWorkspaceService
  -> PostgresWorkspaceUnitOfWork
  -> transaction-local organization/workspace settings
  -> PostgreSQL RLS
```

Workspace creation requires `workspace.create`; metadata/configuration updates require
`workspace.update`; archive requires `workspace.archive`; reads require `workspace.read`.
Restricted memberships see only explicitly granted active workspaces. Service accounts and
system actors require explicit grants from the shared permission vocabulary. RLS remains a
second boundary and rejects missing or cross-tenant context even if repository code errs.

V3.14 exposes this lifecycle through tenant-authorized hosted routes and a server-rendered
organization/workspace experience. See
[`organization-workspace-ux.md`](organization-workspace-ux.md) for routing, BFF, CSRF,
permission-aware controls, pagination, and optimistic-conflict behavior.
