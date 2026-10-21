# Stage 5 authentication: focused session-storage proposal

Status: approved by the subsequent Stage 5 owner request and implemented. This
document retains the reviewed proposal; current commands, defaults and the HTTP
contract are recorded in [backend documentation](../apps/api/DATABASE.md).

## 1. Pre-approval findings and scope

Before approval, the 17 models and revisions `0001_schema` / `0002_reference_data`
include `users.password_hash`, individual roles, enabled state and the unique
`lower(btrim(login_name))` index. They contain no session/revocation repository.
FastAPI exposes `/health`; services accept a trusted `ActorContext` and check
stored roles, but no verified HTTP actor provider existed. Synthetic test hashes
are fixture data, not provisioned accounts or usable authentication credentials.

Within the approved FastAPI/PostgreSQL architecture, a new session table is the
smallest durable solution for server-side logout, expiration and consistency
across workers/restarts. Existing financial audit tables are append-only and
must not become a mutable credential store. Process memory cannot provide shared
durable revocation. A separate file store, SQLite or Redis would introduce another
unapproved persistence/deployment mechanism rather than avoid this decision.

The earlier Stage 5 request required stopping before a necessary schema change.
The subsequent request approved the table and implementation. The original
[database design](database-design-proposal.md),
[implementation plan](database-implementation-plan.md) and
[backend documentation](../apps/api/DATABASE.md) describe the existing foundation;
the latter now records the implemented Stage 5 behavior.

## 2. Proposed eighteenth table: `auth_sessions`

One session belongs to one existing User. Users may have multiple independent
sessions; this proposal does not impose a one-device policy.

| Column | Proposed definition |
| --- | --- |
| `id` | bigint identity primary key; internal reference only. |
| `user_id` | bigint NOT NULL; FK `users.id`, ON DELETE/UPDATE RESTRICT. |
| `token_hash` | bytea NOT NULL UNIQUE; CHECK length = 32; SHA-256 of a random 32-byte authentication token. Never store the raw authentication token. |
| `csrf_token` | bytea NOT NULL; CHECK length = 32; independently generated synchronizer token. Not an authentication credential on its own. |
| `created_at` | timestamptz NOT NULL DEFAULT now(). |
| `last_seen_at` | timestamptz NOT NULL DEFAULT now(); monotonic successful-use time. |
| `expires_at` | timestamptz NOT NULL; fixed absolute deadline assigned by the server. |
| `revoked_at` | nullable timestamptz; set on logout/replacement. |

Name PK/FK/check/unique constraints using the existing metadata convention.
Require finite timestamps, `expires_at > created_at`,
`created_at <= last_seen_at <= expires_at`, and `revoked_at >= created_at` when
present. Index `user_id` for revocation and `expires_at` for cleanup; the unique
hash index serves authentication lookups. No role/name/password snapshots,
employee information, IP addresses or user-agent histories are needed here.

Proposed revision: `0003_auth_sessions`, parent `0002_reference_data`. Create only
this table, checks and indexes; map `AuthSession` in the existing registry. The
application count becomes **18**, plus Alembic bookkeeping. No seed accounts or
alterations to business tables. Downgrade removes only this table and necessarily
invalidates sessions; it must be separately authorized on a real environment.
Existing revisions stay frozen; update the tests that intentionally assert 17.

## 3. Proposed session lifecycle and HTTP boundary

Use a CSPRNG-generated opaque cookie token and store only its verifier hash.
Always generate a fresh token after successful login, revoke any previous valid
session presented by that browser, and atomically insert the new session. Logout
revokes server-side before clearing cookies; a lost response cannot restore it.
Validate expiry/revocation and the current stored user's enabled state/role on
each authenticated request. Resolve `ActorContext(user_id)` only after that check.
These choices follow [OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).

Proposed configurable defaults: **8-hour absolute lifetime, 30-minute idle
timeout**, no sliding absolute extension. Check both deadlines before accepting
or refreshing activity; expired/revoked sessions cannot be resurrected. Serialize
session activity/logout updates and never clear a committed revocation. Future
password/privilege changes must explicitly invalidate affected sessions.

Cleanup: an explicit local maintenance command, scheduled hourly by the operator,
deletes expired or revoked session rows in bounded batches (proposed limit 1,000).
Validation denies them immediately even if cleanup is delayed. Idle-expired rows
can remain until absolute expiry; they must still be denied. Append-only audit
events remain separate and survive cleanup; never log cookie tokens, verifier
hashes, CSRF tokens or password hashes. No maintenance command runs in this stage.

After approval, add only authentication routes: JSON `POST /auth/login`,
`POST /auth/logout`, and `GET /auth/me`. Responses expose approved user identity,
display name and role only, plus the CSRF token where needed by the authenticated
client. Use `Cache-Control: no-store`. No order/import/report routes or frontend.
Unavailable session storage fails closed. No client-managed user/role claims.

HTTPS default: Secure, HttpOnly, SameSite=Lax, Path=/ and no Domain attribute on
the authentication cookie; use a `__Host-` name. A separately selected loopback-only
development profile may use HTTP and a different unprefixed cookie name. Never
infer this profile from a Host header or silently weaken deployment settings.

CSRF proposal: authenticated state-changing requests, including logout, require
the stored synchronizer token in a custom header with constant-time verification,
plus an exact configured trusted-Origin check. Return the CSRF token only to the
validated approved-origin client; it does not authenticate a session. Protect login
itself by requiring JSON, a non-simple custom request header and an exact trusted
Origin; reject absent, null or untrusted origins and deny unapproved credentialed
CORS. No GET may perform logout or other business mutations. SameSite alone is
insufficient. See [OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

## 4. Passwords, permissions and initial Admin

Use PostgreSQL `lower(btrim(login_name))` for lookup, matching the existing index;
do not substitute broader Python case-folding rules. Do not trim passwords.
Return the same failed-login status/message for unknown names, wrong passwords,
disabled accounts or invalid stored hashes, with comparable password-verification
work. Do not expose credential-bearing exception details.

Propose one reviewed Argon2id library (`argon2-cffi`) and salted encoded hashes
in the existing `password_hash` column; rehash when parameters need upgrading.
Benchmark the reviewed settings on the local host, meeting at least the OWASP
Argon2id baseline of 19 MiB, two iterations and parallelism one.
[Password-storage reference](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).
The pre-approval inspection found neither Argon2 library installed. Stage 5 adds
`argon2-cffi==25.1.0` with its required bindings. Never accept the synthetic fixture hash format
as a fallback password algorithm.

Preserve the approved service permissions: both roles perform routine Pending
operations, mark Received, and read sales/SD reports; only Admin reverses Received
or imports employees. Account management and audit access remain Admin operations;
Assistant Admin has no account/security management authority. No site rules.
Do not expose any of those business operations during Stage 5.

Initial Admin proposal: an explicitly invoked, local interactive provisioning
command, outside normal startup and without an HTTP endpoint. Prompt for the
operator-chosen login/display name and twice for a hidden password; reject mismatch
or invalid inputs. Under a transaction-scoped provisioning lock, refuse if **any**
Admin account already exists, including disabled ones. Create exactly one enabled
Admin with an Argon2id hash and an atomic, secret-free provisioning audit attributed
to that new account and explicitly identified as local bootstrap. Roll back both
on failure. Accept no password through command-line arguments and print no hash.
The operator needs authorized local access and explicit database configuration;
this is not a recovery/reset command. No account is created by this proposal.

## 5. Approved scope and verification

The single-table migration, lifecycle, timeout defaults, cookie profiles and local
first-Admin command are approved. Deployment origins remain explicit. Implemented
password/body limits and the bounded login guard are documented in the backend
guide; deployment-wide abuse/TLS/recovery controls still require live-use review.

Then implement incrementally: reviewed migration/model; hashing/session services;
CSRF and authenticated actor dependencies; the three authentication routes and
local provisioning command. No default user, public registration, reset delivery,
in-memory production session substitute or additional business HTTP endpoints.

Use only synthetic users in the verified disposable PostgreSQL harness. Test
upgrade/drift/downgrade, successful login/logout, generic credential failure,
disabled users, normalized login, hash verification, fixed/idle expiry, fixation
resistance, multi-worker revocation, races, cleanup, CSRF/origins, cookie profiles,
actor derivation and existing role rules. Check secrets never enter responses or
logs. Test concurrent first-Admin attempts and rollback, then all existing 150
regression tests, Python 3.13 compatibility and dependency/format checks.

The subsequent owner request explicitly approved the schema boundary. The new
revision and authentication now have synthetic disposable-PostgreSQL tests; see
the backend documentation and current test results for implementation status.
