# Hosted organization and workspace UX

V3.14 turns the V3.5 authorization and V3.6 workspace lifecycle into a hosted product
experience. Organization and workspace IDs in URLs are navigation candidates only. Every
server render and BFF operation sends the authenticated human credential to FastAPI, which
rebuilds `ActorContext`, authorizes current membership and workspace access, creates a sealed
tenant context, and relies on PostgreSQL RLS underneath.

## Scope

Organizations are administratively provisioned for now. The UI lists only active
memberships returned by `/v3/me`; it does not decode Cognito claims to infer membership.
Organization creation, deletion, invitations, role administration, workspace grants, and
ownership transfer are intentionally not exposed in V3.14. The governance services remain
available for a later, explicitly designed administration workflow.

Authorized Owners and Admins can create workspaces, edit metadata and allowlisted
configuration, and archive workspaces. Operators and Viewers see controls according to the
effective permission list returned by the backend. Hidden controls improve usability but are
never an authorization control.

## Routes and data flow

The hosted application uses stable routes:

```text
/app
/app/orgs/{organization_id}/workspaces
/app/orgs/{organization_id}/workspaces/{workspace_id}
/app/orgs/{organization_id}/workspaces/{workspace_id}/settings
/app/orgs/{organization_id}/workspaces/{workspace_id}/incidents/new
/app/orgs/{organization_id}/workspaces/{workspace_id}/incidents
/app/orgs/{organization_id}/workspaces/{workspace_id}/incidents/{incident_id}
/app/orgs/{organization_id}/workspaces/{workspace_id}/incidents/{incident_id}/triage/{triage_run_id}
```

Server Components load memberships, workspace lists, and workspace detail without browser
bearer tokens or shared secrets. Browser mutations use same-origin `/api/organizations/*`
BFF routes, the V3.13 session cookie, and the session-bound CSRF token. Responses are
`no-store`; backend `401`, `403`, `404`, `409`, and validation failures retain distinct safe
browser meanings.

The corresponding FastAPI surface is:

```text
GET   /v3/organizations/{organization_id}/workspaces
POST  /v3/organizations/{organization_id}/workspaces
GET   /v3/organizations/{organization_id}/workspaces/{workspace_id}
PATCH /v3/organizations/{organization_id}/workspaces/{workspace_id}
PATCH /v3/organizations/{organization_id}/workspaces/{workspace_id}/configuration
POST  /v3/organizations/{organization_id}/workspaces/{workspace_id}/archive
```

Workspace lists are bounded to 100 records and use an opaque cursor over deterministic
`(created_at DESC, id DESC)` ordering. Restricted memberships may receive an empty page with
a continuation cursor because authorization filters each bounded candidate page.

## Configuration and concurrency

The UI renders only the V3.6 schema-version-1 allowlist:

- `rag_top_k`, integer 1 through 64;
- `llm_temperature`, number 0 through 2.

Metadata and configuration have independent optimistic versions. The BFF carries the
observed version on every update. A stale write receives `409`, is not applied, and offers a
reload action. Unknown configuration and secret-like keys are rejected by the API schema and
domain allowlist.

Workspace archive is confirmed explicitly and never performs physical deletion. Archived
workspaces retain incidents, triage, evidence, and audit history, while V3.6 authorization
blocks new reads and mutations through the active-workspace path. Restore remains deferred.

## Compatibility and deferred work

The Version 2 static frontend, filesystem workspaces, API keys, CLI, Gradio, local FAISS, and
synchronous triage remain unchanged. V3.15 incident and triage history/detail behavior is
documented in [`incident-history.md`](incident-history.md).
CloudWatch onboarding and integration setup remain V3.16 and later.

The V3.13 Cognito compatibility constraint also remains: first-sign-in identity mapping
currently needs email/display attributes at mapping time, while standard Cognito access
tokens do not necessarily carry them. V3.22 must validate access-token customization, a
trusted server-side identity enrichment path, or a stable-subject-only first-sign-in change.
V3.14 does not weaken token verification to conceal this deployment decision.
