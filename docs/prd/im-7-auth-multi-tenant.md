# IM-7 — Auth / multi-tenant support

**Type:** Story **Epic:** Platform **Priority:** P1 — do before IM-8 and before data volume grows
**Estimate:** 13 points **Depends on:** IM-1 (in practice, retrofits IM-1→IM-6)
**Branch:** `feat/server/auth-multi-tenant` then `feat/client/auth-ui`

## Context

Everything shipped so far is single-tenant and unauthenticated: any caller can read any dataset.
Customer feedback contains PII (`customer_id`, free-text complaints), so this is a prerequisite for
any deployment beyond a developer laptop. Retrofitting tenancy gets more expensive with every table
added — hence P1 and hence "before IM-8".

## Design decisions taken in this PRD

These are **assumptions, not open questions**. Challenge them during `/spec-plan` if you disagree;
otherwise build to them.

| Decision              | Choice                                                                             | Rationale                                                                                                                                                                    |
| --------------------- | ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tenancy model         | Shared database, shared schema, `organization_id` FK on every tenant-owned table   | Simplest to operate with no Docker and a developer-provided Postgres; avoids per-tenant migration fan-out                                                                    |
| Isolation enforcement | Application-layer, via a mandatory scoped-session dependency                       | Postgres RLS is stronger but adds migration and connection-role complexity disproportionate to this stage. **Record RLS as a documented future hardening step in the spec.** |
| AuthN                 | Email + password (Argon2id), short-lived JWT access token + rotating refresh token | Self-contained; no external IdP dependency for a product still finding its shape                                                                                             |
| Roles                 | `owner`, `member`                                                                  | Two roles cover invite/manage vs use. Do not build a general RBAC system                                                                                                     |
| Signup                | Invite-only within an org; the first user creating an org becomes `owner`          | Prevents open registration on a data-sensitive product                                                                                                                       |

## Scope

**In scope**

- `organizations`, `users`, `memberships`, `refresh_tokens` tables + migrations.
- Adding `organization_id` to `datasets` (and, transitively, scoping every child read).
- Auth endpoints; a FastAPI dependency that yields the authenticated user + org.
- Retrofitting **every existing endpoint** from IM-1→IM-6 to scope by org.
- A backfill migration that assigns pre-existing data to a default org.
- Login UI, session handling, and route protection in the client.

**Out of scope**

- SSO / SAML / OAuth providers.
- Per-dataset ACLs within an org. Org membership grants access to all of the org's datasets.
- Billing, quotas, usage metering.
- Password reset via email (no mail infrastructure exists). Ship an owner-initiated password reset
  instead and note the gap.

## Technical approach

- **Scoping.** `datasets.organization_id` is the tenancy root. Child tables (`feedback_items`,
  `clusters`, `cluster_assignments`, `conversations`, …) inherit scope through their FK chain to
  `datasets`. **Every query that reaches a tenant-owned table must go through a repository/service
  function that takes the org ID** — no ad-hoc `session.query(Dataset).get(id)` in a route handler.
- **The unauthorised-access response is 404, not 403,** for resources belonging to another org. A
  403 confirms the resource exists and leaks tenant information.
- **Password hashing:** Argon2id via `passlib` or `argon2-cffi`. Never store or log a plaintext
  password. `SECRET_KEY` must have **no default value** in `Settings` — the app must fail to start
  if it is unset in a non-development environment.
- **Tokens:** JWT access token, short TTL (default 15 min); opaque refresh token, hashed at rest,
  rotated on use, revocable. Reuse of a rotated refresh token invalidates the whole family.
- **Backfill migration:** creates a `Default Organization`, sets `organization_id` on all existing
  `datasets`, then applies the `NOT NULL` constraint. It must be a single migration that is safe to
  run against a populated database, and it must be reversible.
- **Client:** an `AuthContext` in `client/src/store/` holds the session; the generated client is
  configured with a request interceptor that attaches the bearer token and triggers refresh on 401.
  Protected routes redirect to login. **Do not hand-edit `client/src/api/`** — configure the
  generated client from `client/src/lib/apiClient.ts`, which already exists for exactly this.
- **CORS:** `cors_origins` already exists in settings; ensure credentials handling matches the token
  transport chosen in the spec.

## API contract

```
POST /auth/register        { email, password, organization_name }  → 201 (creates org + owner)
POST /auth/login           { email, password }                     → 200 { access_token, refresh_token, expires_in }
POST /auth/refresh         { refresh_token }                       → 200 { access_token, refresh_token }
POST /auth/logout          (revokes the presented refresh token)   → 204
GET  /auth/me                                                       → 200 { user, organization, role }

POST /organizations/invitations   (owner only)   { email, role }   → 201
POST /auth/accept-invitation      { token, password }              → 201
GET  /organizations/members       (any member)                     → 200
```

Every existing endpoint gains an `Authorization: Bearer <jwt>` requirement.

## New configuration

`SECRET_KEY` (**no default — required**), `ACCESS_TOKEN_TTL_MINUTES` (default `15`),
`REFRESH_TOKEN_TTL_DAYS` (default `30`), `PASSWORD_MIN_LENGTH` (default `12`).

## Acceptance criteria

1. Every endpoint added in IM-1→IM-6 returns **401** without a valid bearer token. A test enumerates
   the app's routes and asserts each non-public one rejects an anonymous request — so a future route
   cannot silently ship unprotected. Public exceptions: `/health` and the `/auth/*` entry points.
2. A user in org A requesting a dataset owned by org B receives **404**, not 403 and not 200.
3. The same 404-not-403 rule holds for every nested resource: clusters, cluster items, the cluster
   map, embedding/summarization job status, and conversations.
4. `POST /auth/register` creates an organization and its first `owner` in one transaction; a
   duplicate email returns **409**.
5. Login returns an access token and a refresh token; the access token expires after
   `ACCESS_TOKEN_TTL_MINUTES` and an expired token yields **401**.
6. Refresh rotates the refresh token. Presenting a previously rotated refresh token yields **401**
   and revokes the entire token family.
7. Passwords are stored as Argon2id hashes. No plaintext password appears in the database, in logs,
   or in any API response — asserted by a test that greps captured log output.
8. The application **fails to start** when `SECRET_KEY` is unset outside development.
9. An `owner` can invite a `member`; a `member` receives **403** when calling an owner-only endpoint.
10. The backfill migration runs against a database populated by IM-1→IM-6, assigns all existing
    datasets to a default organization, applies `NOT NULL`, and downgrades cleanly.
11. Every new query path is org-scoped through the shared dependency. A code review checklist item —
    and a test — confirms no route handler queries a tenant-owned table without an org filter.
12. The client attaches the bearer token to every request via `client/src/lib/apiClient.ts`,
    transparently refreshes on 401, and redirects to login when refresh fails.
13. `client/src/api/` shows only generated changes.
14. `pnpm --filter client build` passes.

## Test plan

- **Cross-tenant isolation suite** (the centrepiece): seed two orgs each with a full pipeline's
  worth of data, then assert that every read endpoint returns 404 for the other org's IDs. This
  suite should be the hardest thing in the repo to accidentally break.
- Route-coverage test: introspect `app.routes` and assert each non-public route rejects anonymous
  requests.
- Auth unit tests: hashing round-trip; token expiry; refresh rotation; rotated-token reuse revokes
  the family; role enforcement.
- Migration: run against a populated database; verify counts before/after; verify downgrade.
- Manual: two browser profiles, two orgs, confirm no data bleed.
- Run `/security-review` on the branch before opening the PR.

## Definition of done

Two PRs (backend, then frontend), each squash-merged. `/security-review` run and its findings
addressed or explicitly triaged in the PR. `README.md` "Getting Started" updated with the
`SECRET_KEY` requirement.
