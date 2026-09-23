# Version 3 Authentication Boundary

V3.4 establishes hosted identity and `ActorContext`. It answers who the actor is. V3.5
will decide what that actor may do. The hosted Next.js browser session is implemented in
V3.13, not V3.4.

## Trust Chain

```text
Cognito JWT
    -> verify identity
    -> ActorContext
    -> V3.5 membership/RBAC authorization
    -> authorized organization/workspace context
    -> transaction-local PostgreSQL RLS context
```

JWT organization, workspace, and role claims are never tenant authorization. Authentication
does not construct `TenantContext` or call the PostgreSQL RLS context helper.

## ActorContext

`ActorContext` is immutable and contains:

- an existing domain `ActorReference` for a human, service account, or system actor;
- the authentication method;
- provider issuer and stable subject where applicable;
- the public service-account credential lookup ID where applicable;
- optional request correlation metadata.

It contains no password, token, service-account secret, membership, role, organization ID,
or workspace ID. Its `repr` and `safe_log_fields()` omit provider subjects and credential
material. Provider subjects can be personal or operationally sensitive and should appear
only in restricted identity diagnostics when strictly necessary.

## Human Tokens

The hosted API verifier is compatible with Cognito OIDC JWTs. Configuration is optional so
Version 2 commands do not require Cognito:

- `AIRA_OIDC_ISSUER`
- `AIRA_OIDC_CLIENT_ID`
- `AIRA_OIDC_TOKEN_USE` (`access` by default, or explicitly `id`)
- `AIRA_OIDC_JWKS_URL` (defaults to `<issuer>/.well-known/jwks.json`)
- `AIRA_OIDC_ALGORITHMS` (explicit RSA allowlist, `RS256` by default)
- `AIRA_OIDC_LEEWAY_SECONDS`
- `AIRA_OIDC_JWKS_CACHE_SECONDS`
- `AIRA_OIDC_HTTP_TIMEOUT_SECONDS`

The verifier requires HTTPS issuer/JWKS URLs and validates signature, issuer, expiry,
not-before when present, token use, stable subject, and client identity. Cognito access
tokens use `client_id`; ID tokens use `aud`. Hosted API clients should use access tokens.
Raw JWTs are neither logged nor persisted.

JWKS keys are cached for a bounded TTL. An unknown `kid` causes one controlled refresh.
If an expired cache cannot refresh, or the requested key remains unknown, verification
fails closed. A cached key is not accepted beyond its TTL after a network failure.

The initial identity binding is the exact `(issuer, subject)` pair stored on `users`.
Email is mutable profile metadata and never an identity key. First sign-in requires email
and display-name claims to create the local user; later verified claims may update those
fields. A disabled local user fails authentication. Supporting multiple external identities
for one AIRA user will require a separate identity-link table in a later explicitly scoped
migration; identities must never be joined automatically by matching email.

## Service Accounts

External machines use AIRA service accounts, not Cognito human identity. Credentials have
this shape:

```text
aira_sa_<public-lookup-id>.<random-secret>
```

Both components are generated with a cryptographically secure random source. The complete
credential is returned once. PostgreSQL stores the public lookup ID, a random salt, and a
salted `scrypt-v1` verifier; plaintext secrets are never persisted. Verification uses
constant-time comparison. Credentials can expire, rotate, and be revoked, and successful
use updates `last_used_at`. Rotation revokes prior active credentials. Disabling the service
account rejects all of its credentials.

Service-account and credential records retain the actor that created them; rotation records
the revoking and replacement actor, and account disablement records its actor. Tenant-scoped
audit events for management operations require V3.5 authorization and are not fabricated
before an organization relationship exists.

Service accounts receive no organization/workspace access or RBAC scope in V3.4. V3.5 must
define and authorize that relationship.

## System Actors And Jobs

System actors are constructed explicitly only after trusted composition code verifies a
workload identity. Public request authentication accepts only `Bearer` and
`AiraServiceAccount` schemes; callers cannot submit `actor_type=system`.

Future API and worker services are expected to use AWS IAM/workload identity for service
authentication. Queue messages may carry identifiers for correlation, but a worker must
load authoritative job/actor state and must not trust actor or tenant assertions from a
message payload. AWS workload infrastructure is outside V3.4.

## FastAPI Contract

`HostedActorDependency` is an injectable authentication seam for future hosted routes:

```text
Authorization: Bearer <OIDC access token>
Authorization: AiraServiceAccount <opaque AIRA credential>
```

It returns `ActorContext` or a generic `401 Unauthorized`. It is intentionally not attached
to existing routes. Version 2 continues to use `API_KEY` and `ADMIN_API_KEY` through its
existing self-hosted composition.

## V3.13 Browser Session Contract

V3.13 will implement Cognito Authorization Code Flow with PKCE in the server-capable hosted
Next.js service. The Next.js server owns authorization redirects, state/nonce/PKCE checks,
the callback, token refresh, logout, and expiry. Browser session cookies must be `Secure`,
`HttpOnly`, appropriately `SameSite`, narrowly scoped, rotated against fixation, and backed
by CSRF protection for state-changing requests.

Refresh and access tokens must not be stored in `localStorage` or `sessionStorage`. Shared
AIRA API/admin keys must not appear in browser code or bundles. The Next.js server calls the
hosted API using the verified access-token contract above. Session behavior, cookie code,
frontend route protection, and associated tests remain V3.13 work.
