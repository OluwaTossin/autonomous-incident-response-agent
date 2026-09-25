# Hosted web application

V3.13 adds `web/`, an independently buildable, server-capable Next.js 15 application. It
does not modify `frontend/`: the Version 2 UI remains a static export served by nginx or
S3/CloudFront and continues to use its existing self-hosted API-key model. The hosted app
uses no `NEXT_PUBLIC_*` API key, admin key, token, database URL, or provider secret.

## Runtime boundary

```text
Browser
  -> Next.js /auth/login (state + nonce + PKCE transaction)
  -> Cognito /oauth2/authorize
  -> Next.js /auth/callback
  -> Cognito /oauth2/token (server-side code exchange)
  -> Next.js opaque PostgreSQL session
  -> protected /app Server Component
  -> same-origin Next.js /api/* BFF
  -> hosted FastAPI bearer boundary
  -> ActorContext -> RBAC -> authorized tenant context -> RLS
```

The hosted browser never calls FastAPI directly. FastAPI does not understand the browser
cookie. Candidate organization/workspace IDs cross the BFF, but `/v3/me` and every resource
operation re-authorize them in the Python application. V3.13 adds only the `/v3/me`
bootstrap needed to return the internal user ID and currently authorized organizations,
roles, permissions, and workspaces. Management UX remains V3.14.

## Login and session security

`GET /auth/login` generates cryptographically random state, nonce, PKCE verifier, and an
opaque transaction ID. PostgreSQL stores the transaction-ID/state digests, a short expiry,
the validated local return path, and an AES-256-GCM encrypted nonce/verifier. Callback use
atomically consumes the transaction before comparison, so mismatches, expiry, and replay
fail closed. Only `/app` local paths are accepted as return targets.

The callback exchanges the code server-side, verifies the ID-token signature, issuer,
audience, expiry, `token_use=id`, and nonce, then verifies access-token issuer, expiry,
`token_use=access`, and `client_id`. It calls `/v3/me` with that access token before creating
a new session. The transaction ID is never reused as a session ID.

`browser_sessions` stores a session-ID digest, internal/provider identity metadata,
inactivity and absolute deadlines, revocation, optimistic version, CSRF digest, and encrypted
provider credentials. The cookie contains only the random session ID. Access tokens refresh
server-side near expiry; compare-and-swap versioning prevents an older concurrent refresh
from overwriting newer credentials. Failed refresh revokes the local session. Local logout
always revokes PostgreSQL state and clears the cookie; optional Cognito logout is a redirect,
not a claim that global token revocation occurred.

Default lifetimes are 10 minutes for a login transaction, 60 minutes of inactivity, and 12
hours absolute. Provider-token expiry is independent: it triggers refresh but never extends
the absolute browser lifetime.

## BFF and browser controls

Protected pages validate the session before rendering. Authenticated pages, callbacks, and
BFF responses use dynamic/no-store behavior. Mutations require the exact configured Origin
and a session-bound synchronizer token. A backend `401` revokes the local session; `403`,
validation, missing-resource, conflict, and unavailable responses remain distinct safe
browser errors. Authorization headers, provider responses, SQL errors, and internal URLs are
never mapped into browser responses.

The initial UI creates an incident, requests asynchronous triage, polls with bounded backoff
while the page is visible, stops at terminal backend states, renders evidence/results/failure,
and requests cancellation. It does not reproduce the backend state machine.

Global headers include CSP, frame denial, content-type sniffing protection, strict referrer
policy, restricted browser capabilities, and production HSTS. Next.js currently requires
`'unsafe-inline'` for framework bootstrap scripts and generated styles; production excludes
`'unsafe-eval'`, while development permits it for tooling. This allowance should be replaced
with request nonces if the selected Next.js release and deployment path support that without
breaking streaming.

## Configuration and local development

Copy placeholders from `web/.env.example` into an uncommitted `web/.env.local`. The API and
web server use the same Cognito app-client ID and issuer. `AIRA_WEB_DATABASE_URL` uses the
runtime `aira_app` role and standard Node PostgreSQL URL syntax. Generate the encryption key
with a cryptographically secure 32-byte source and base64 encode it.

```bash
docker compose -f docker-compose.hosted-db.yml up -d
AIRA_DATABASE_MIGRATION_URL=postgresql+psycopg://... uv run alembic upgrade head
cd web
npm ci
npm run dev -- --port 3001
```

Automated tests inject the OIDC provider and session store and do not contact Cognito. Run
`npm test`, `npm run typecheck`, `npm run lint`, and `npm run build` in `web/`. The standalone
container exposes `/healthz`; ECS service, target group, HTTPS ALB rules, deployment secrets,
and production Cognito resources remain V3.22 work. Organization/workspace administration
is described in [`organization-workspace-ux.md`](organization-workspace-ux.md). Full incident
history remains V3.15.
