# Version 3 Authorization And RBAC

V3.5 answers what an authenticated actor may do. Authentication produces an immutable
`ActorContext`; it does not grant tenant access. Authorization resolves current durable
AIRA records for every decision and returns a sealed `AuthorizedTenantContext` only after
the requested organization, workspace, and capability have all been verified.

## Permission Matrix

Organization creation is a special authenticated-human bootstrap operation. The creator
becomes the first active, unrestricted Owner. It is not inherited from an existing role.

| Permission | Owner | Admin | Operator | Viewer |
|---|:---:|:---:|:---:|:---:|
| `organization.read` | Yes | Yes | Yes | Yes |
| `organization.update` | Yes | Yes | No | No |
| `organization.transfer_ownership` | Yes | No | No | No |
| `membership.read` | Yes | Yes | No | No |
| `membership.invite` | Yes | Yes | No | No |
| `membership.update` | Yes | Yes | No | No |
| `membership.remove` | Yes | Yes | No | No |
| `workspace.read` | Yes | Yes | Yes | Yes |
| `workspace.create` | Yes | Yes | No | No |
| `workspace.update` | Yes | Yes | No | No |
| `workspace.archive` | Yes | Yes | No | No |
| `incident.read` | Yes | Yes | Yes | Yes |
| `incident.create` | Yes | Yes | Yes | No |
| `triage.run` | Yes | Yes | Yes | No |
| `job.read` | Yes | Yes | Yes | Yes |
| `job.create` | Yes | Yes | Yes | No |
| `job.cancel` | Yes | Yes | Yes | No |
| `job.retry` | Yes | Yes | Yes | No |
| `job.execute` | No | No | No | No |
| `knowledge.read` | Yes | Yes | Yes | Yes |
| `knowledge.manage` | Yes | Yes | Yes | No |
| `integration.read` | Yes | Yes | Yes | Yes |
| `integration.manage` | Yes | Yes | No | No |
| `action.read` | Yes | Yes | Yes | Yes |
| `action.propose` | Yes | Yes | Yes | No |
| `approval.read` | Yes | Yes | Yes | Yes |
| `approval.request` | Yes | Yes | Yes | No |
| `approval.decide` | Yes | Yes | No | No |
| `execution_intent.read` | Yes | Yes | Yes | Yes |
| `execution_intent.prepare` | Yes | Yes | No | No |
| `execution_intent.cancel` | Yes | Yes | No | No |
| `usage.read` | Yes | Yes | No | No |
| `audit.read` | Yes | Yes | Yes | No |
| `service_account.read` | Yes | Yes | No | No |
| `service_account.manage` | Yes | Yes | No | No |

Owner and Admin differ intentionally: only an Owner may transfer ownership. An Admin may
manage non-Owner memberships but may not suspend, remove, demote, or create an Owner.
Permission checks use the centralized matrix, not scattered role-name conditions.

V3.19 uses `action.propose` only at the trusted application/worker generation boundary.
There is no browser endpoint that accepts an `ActionProposal` payload, so a human role or
service-account grant cannot use this vocabulary entry to forge executable intent.
`action.read` protects proposal routes. V3.20 uses `approval.request` for Owner, Admin, and
Operator review requests and `approval.decide` for Owner/Admin decisions. Both operations
require a human `ActorContext`, and the requester cannot approve or reject their own request.
See [`approvals.md`](approvals.md). This does not change the no-arbitrary-payload rule.
V3.21 gives every incident reader intent inspection, while only Owner/Admin may prepare or
cancel an intent. Service accounts receive none of these permissions by default. See
[`execution-intents.md`](execution-intents.md).

V3.24 keeps `usage.read` Owner/Admin-only and applies it to workspace usage/quota summaries.
No browser permission raises quotas, and no quota mutation endpoint is exposed. See
[`usage-quotas.md`](usage-quotas.md).

## Membership Lifecycle

Membership state progresses through `invited -> active -> suspended/revoked` and
`suspended -> active/revoked`. A revoked row may be re-invited, preserving the unique
organization/user identity while issuing a fresh invitation state. Invited, suspended,
and revoked memberships grant no access.

Every organization must retain at least one active Owner. Demotion, suspension, and
removal lock the organization row before counting active Owners, so concurrent changes
cannot independently remove the final Owner. Ownership transfer promotes another active
member to unrestricted Owner and demotes the current Owner to Admin in one transaction.

## Workspace Restrictions

An organization membership establishes role permissions. Its workspace mode is either:

- `all`: role permissions apply to every active workspace in the organization;
- `restricted`: workspace-scoped permissions apply only to explicit workspace grants.

Restrictions only narrow access and never create membership. Restricted members cannot
create workspaces. Owners are always unrestricted. Workspace grants have composite tenant
foreign keys and RLS, so a grant cannot point across organizations. Archived organizations
or workspaces fail authorization even when a membership or grant still exists.

## Machine Actors

Service-account credentials prove identity only. A separate durable organization grant
contains an allowlisted subset of the same permission vocabulary and an optional workspace
restriction. Service accounts cannot receive organization administration, membership,
approval request/decision, usage, audit, or Owner capabilities. Grants are independently revocable
and changes are audited.

System actors have no automatic bypass. They require an exact composition-owned policy
matching system name, workload issuer, workload subject, organization, permissions, and
optional workspace set.

`job.execute` is reserved for explicitly granted workload identities. Human roles and
external service-account grants cannot claim or complete hosted jobs. External service
accounts may receive the separately grantable read/create/cancel/retry capabilities.

## Authorization To RLS

The trust chain is:

```text
verified ActorContext
  -> actor-self membership or service-account grant lookup
  -> centralized permission and workspace policy
  -> active organization/workspace validation
  -> sealed AuthorizedTenantContext
  -> transaction-local PostgreSQL tenant settings
  -> RLS-protected repository work
```

Actor-self authorization lookups use narrow SELECT-only RLS policies and transaction-local
actor settings. They do not establish tenant settings. Only `AuthorizationService` can
construct `AuthorizedTenantContext`; request and JWT organization, workspace, and role
values cannot construct it or set RLS context. PostgreSQL RLS remains independent defense
in depth after the application decision, and pooled-connection tests verify settings do
not survive a transaction.

## Audit And Compatibility

Organization creation, invitation, activation, role/state changes, ownership transfer,
workspace restriction changes, and service-account grant changes write durable PostgreSQL
audit events in the same transaction as the change. Events contain actor, organization,
optional workspace scope, action, target, timestamp, correlation, and relevant details.

This hosted authorization composition does not alter Version 2 API/admin keys, filesystem
workspaces, local FAISS, JSONL audit, or self-hosted runtime behavior. Hosted routes and the
Next.js session flow remain later-phase work.

V3.6 applies this boundary to durable workspace lifecycle and configuration as documented
in [`workspaces.md`](workspaces.md).

V3.7 applies `knowledge.read` to document metadata/download and `knowledge.manage` to
upload, version, archive, and failed-object cleanup as documented in
[`documents.md`](documents.md). Object keys never grant access independently.
