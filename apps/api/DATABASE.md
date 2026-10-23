# Database foundation and backend services

The package `asi_meal_api.db` registers 18 typed SQLAlchemy models without opening
connections. Alembic owns schema changes; no `create_all`, automatic migration on
application startup or runtime database URL default is used. Stage 6 exposes
authenticated business endpoints as described below. The Stage 2–5 sections
record the boundaries at those stages; Stage 6 supersedes their statements that
business HTTP integration is absent.

## Migrations

- `0001_schema`: 17 tables, named restrictive FKs/checks/unique constraints,
  report/history indexes, exact numeric line totals, and the frozen integrity SQL
  alongside the revision. It does not import current model definitions to create
  tables, so later model edits cannot silently change the revision.
- `0002_reference_data`: exactly two roles, three configurable item category
  prices (50/75 including rice, extra rice 15), and five payment categories.
  No accounts, employee/visitor/order data, or For Deposit. Running an already
  applied head does not reset prices. Reference-data downgrade refuses removal
  when restrictive business FKs still depend on those rows.
- `0003_auth_sessions`: the approved eighteenth table, restrictive User FK,
  unique 32-byte token digest, independent CSRF token, finite/ordered timestamps,
  expiration/revocation and user/expiry indexes. Prior revisions are unchanged.
  Downgrade removes only session storage and requires separate authorization on
  real targets; its upgrade/rollback/re-upgrade are tested on disposable data.
- `0004_super_admin`: extends the allowed role constraint and inserts the role;
  it does not promote existing users. Downgrade refuses while any user references
  Super Admin. `0005_password_change_required` adds the mandatory-change flag,
  defaulting to false for existing users. Downgrades require separate review.

Stage 14F.3 adds authenticated Super Admin-only `GET`/`POST /api/users` and
`PATCH /api/users/{id}`. Account creation or reset requires an administrator-entered
temporary password; the recipient must change it using `POST /auth/change-password`
before ordinary protected operations. Login, session check, password change, and
logout remain available in that restricted state. Role changes, resets and
deactivation revoke sessions atomically with the account update and audit event;
password change revokes other sessions. Account administration cannot create,
disable or demote Super Admins through HTTP. The local promotion operator is
self-attested, not authenticated as the target account. Audit records exclude
passwords and session secrets. Stage 14F.4 adds read-only Super Admin-only
`GET /api/activity` and `GET /api/activity/{event_id}`. The listing accepts
inclusive Philippine dates, actor ID, action, entity and reference filters,
bounded limits and a filter-bound newest-first cursor. Both endpoints return
allowlisted fields only; employee references, raw audit JSON, session IDs and
free-text correction explanations are excluded. Correction reason labels come
from the approved reason codes. Actor names are current, not historical snapshots.
Only actions actually recorded can appear; unsuccessful login attempts and
ordinary reads are examples of gaps. No migration was added for this view;
global audit scans may need an index after measurement on realistic data.

For an authorized rollout, verify the database identity, preserve backups and
apply both migrations before deploying the matching backend and frontend. Follow
the [local demo runbook](../../docs/local-demo-runbook.md) for the explicit
promotion procedure. Do not upgrade or promote the currently running demo without
a separately authorized rollout.

For a separately authorized target, run Alembic from `apps/api` with an explicitly
supplied `ASI_DATABASE_URL` using the `postgresql+psycopg` dialect. Keep its value
outside version control and logs. Offline SQL generation needs no database URL.
Package `alembic.ini`, the Alembic environment/revisions, and the revision SQL
asset together when a future deployment/migration runner is authorized. The
existing API image/start command has not been changed into a migration runner.

## Integrity boundary

Immediate guards validate order date/menu assignment, new-line menu membership
and snapshots, immutable recorded identity/date/menu, and Pending-only child
edits. Order creation locks its date assignment and menu; child writes lock the
order and selected source records. Referenced offerings cannot move between
menus/dishes. Offering creation/reclassification matches the catalog category,
but later catalog changes never cascade to configured offerings or recorded sales.
Unchanged lines keep their snapshots even while a Pending quantity changes.

Deferred constraint triggers validate committed nonempty orders, visitor
Finance-only allocations, and exact allocation equality for Received orders.
They run on order, item and allocation changes. Deferral allows atomic entry and
rebalancing; it is not an external payment check or receivables workflow. The
approved positive-price case is supported; zero-total Received orders cannot
satisfy positive allocations and need a separately confirmed policy if ever required.

Audit and receipt events reject UPDATE/DELETE. Receipt events identify the same
order as their audit event. Reasons retain stable codes/label snapshots and Other
requires a non-whitespace explanation; retired codes can remain in historical rows.
Current-list validation and the named confirmation checkbox belong to the future
authenticated correction interface, not to the database's historical vocabulary.

The schema supports one transaction containing a state change and its events,
but does not automatically fabricate actors/audit entries for arbitrary SQL.
The Stage 2 services below enforce order permissions and atomic audit writes.
Catalog price-confirmation features and business HTTP integration remain
unimplemented. Authentication is described below. No test proves completed payroll, GCash
verification, or production security.

Use a migration-owner database role only for reviewed migrations. A later runtime
role must be a non-owner without DDL/TRUNCATE, trigger-disabling, or audit/event
UPDATE/DELETE permissions; deny undefined sensitive application permissions.
No production roles, passwords, grants, or login accounts are provisioned here.
Even an append-only trigger is not protection against an unrestricted DB owner.

Employee columns use the approved minimal mapping: employee number, full name,
and optional position/campaign/line of business. No contact fields or invented
eligibility rules. Import jobs/results store counts, outcomes, row numbers and
safe field/error codes, not raw exports. The Stage 3B service below implements the
approved import policy without adding authenticated HTTP exposure.

## Stage 2 service boundary

`asi_meal_api.orders.OrderService` accepts a synchronous session factory. Each
public call creates a fresh session and owns its transaction, including commit
and rollback; callers must not reuse a session with pending unrelated writes.
These order services create no global engine, default connection, accounts or
HTTP routes. FastAPI exposes health and the three authentication routes only.

`ActorContext(user_id)` is an explicit **trusted caller** contract, not an
authentication mechanism. The Stage 5 verified session dependencies construct
it separately from request bodies. Never deserialize it from browser input or
treat knowledge of an ID as authentication. The service rechecks the stored user's
enabled flag and role under a shared lock; it accepts no caller-supplied role/name.
The future correction form must obtain the display name through that verified
session and show `I, {display name}, confirm this change.` before submission.
The service requires a literal checked boolean for reversal; no UI exists yet.

- Both roles can create Pending orders, edit permitted Pending details, and mark
  Received. Only Admin can reverse Received. Disabled/missing actors are denied.
- Creation validates the selected date/menu and existing customer, captures
  server-owned customer/item snapshots, and consolidates repeated allocation
  categories. Visitors use Finance only. Amounts are Decimal with exact centavos;
  quantities are positive database integers. Pending allocations may be incomplete;
  Received requires positive allocations summing exactly to the snapshot total.
  When a visitor order is marked Received, Finance is set to its recorded item
  total in the same transaction, with the allocation change in the receipt audit's
  before/after snapshots. Employee allocations remain subject to the balance check.
- Edits accept quantity changes, added/removed lines, and a replacement allocation
  set. `allocations=None` preserves it; `()` clears it while Pending. No customer,
  date/menu, snapshot price, identity or metadata edit fields are accepted. Existing
  lines retain their snapshots; newly selected lines use locked offerings from
  the recorded menu, even after the date is assigned a different menu.
- Order creation, permitted edits and actual status transitions append audits
  within their transaction. Status transitions also append a typed receipt event
  with the same actor/time/status history. Corrections preserve the stable reason
  code, current label snapshot, trimmed explanation and acknowledgement. The five
  reasons live in one small immutable server-side mapping, without a settings UI;
  Other requires non-whitespace text. Historical events never read today's labels.
- Every edit/transition requires the expected version, checks it after locking
  the order, and rejects stale writes. Current-state retries with the current
  version create no events; an old version remains stale even across a reversal.
  No-op edits create neither audit events nor version changes.
- Create retries serialize by transaction advisory lock derived from the UUID;
  its unique constraint remains the final guard. Matching uses the original
  normalized request saved in the creation audit, including item order and summed
  allocation amounts. A match returns the existing order's current result, even
  after edits; a conflict or absent original audit fails closed. No snapshots are
  refreshed on retry. IDs in the restricted audit provide necessary traceability;
  no passwords, contact details or raw imports are recorded by these services.
- Lock order is actor, then request-key lock (create only), then date/menu/sorted
  offerings for creation; existing writes lock the order before any recorded-menu
  and sorted-offering locks. Customer snapshots are read under shared locks.
  Future catalog/import writers must coordinate with this discipline. Constraint
  triggers remain the database backstop. No schema/migration changes were needed.

Received contribution remains a function of current status, with no counters.
There is no refund, cancellation, partial-payment ledger, external verification,
report generation or authentication implementation in these order services.

## Stage 3B employee import service

`asi_meal_api.employee_imports.EmployeeImportService` uses the same fresh-session
factory convention and trusted `ActorContext` boundary as the order service.
Only an enabled stored Admin may execute it; role/identity never comes from CSV
or an ordinary request body. No upload endpoint or authentication was added.
See [the import specification](../../docs/hrms-import-specification.md).

`import_csv(actor, bytes_or_binary_stream)` reads the stream from its current
position. It records a processing job, strictly parses the whole UTF-8 CSV with
optional BOM, then applies valid rows in one transaction. All ten headers must
match exactly by name; rearrangement is allowed. Only the five mapped employee
fields survive parsing. Blank optional values retain existing data. Unchanged
employees, absent employees and historical order snapshots remain untouched.

A transaction-scoped advisory lock serializes imports before current-employee
comparison, followed by employee locks in identifier order. Employee changes,
outcomes, counts and audits commit together. Validation/apply failures return a
durable failed `ImportResult`, with zero employee changes and safe field/error
codes. Complete rejected batches mark all rows rejected, distinguishing actual
errors from `BATCH_NOT_APPLIED`. Fatal incomplete parses have unknown row counts,
represented by zero counters and no row records. Raw file/contact values and
database exception messages are never saved in diagnostics or logged here.

Failure history is saved separately after rollback. A durable completed result
is preserved if a commit acknowledgement fails; if the result/history cannot be
confirmed, `ImportHistoryError.import_id` identifies the job for investigation.
Unreadable/nonbinary sources raise `ImportSourceError` before job creation because
no complete source hash exists. Intentional re-imports create new jobs, not new
employee identities; the hash imposes no retry ban. No files are written to disk.

The Stage 3B owner request approves whole-file rejection, blank-value retention
and Admin-only execution, replacing the specification's previous approval gates.
The exact header contract is retained. Upload limits, freshness responsibility,
history access/retention and interrupted-job recovery remain live-use decisions.
No models, migrations, dependencies or existing order services were changed.

## Stage 4 operational reporting

`asi_meal_api.reports.ReportingService` accepts a factory of fresh independent
Engine-bound Sessions. It provides `sales_summary`, `payment_summary`,
`salary_deduction_report` and `report_bundle`, each taking a trusted `ActorContext`
and `DateRange`. Both enabled stored Admin and Assistant Admin may read these
operational reports. There is no authenticated HTTP endpoint, default identity,
or change to audit-history access. Employee/SD results require protected access
when a real session provider is integrated; these services do not log results.

The Stage 4 owner request settles these initial operational defaults:

- Filter by the original `orders.service_date`, using explicit Philippine
  (`Asia/Manila`) calendar dates. `DateRange.daily(day)`, `weekly(containing_date)`
  and `monthly(year, month)` construct periods; `DateRange(start, end)` is custom.
  Weeks run Monday through Sunday; months are calendar months; both endpoints
  are inclusive. Strings, timestamps, invalid months and reversed ranges fail.
  There is no implicit today/UTC conversion, and original audit timestamps remain
  untouched. These defaults supersede earlier unresolved operational report-date
  questions; payroll cutoffs and finalization remain unapproved.
- Only current Received orders contribute. No counters, stored summaries or
  materialized views are introduced. A reversal affects new reports immediately;
  re-marking restores the order once. A report already in progress consistently
  retains its starting snapshot, rather than mixing old and new totals.
- Each call owns a PostgreSQL `REPEATABLE READ`, `READ ONLY` transaction, including
  stored-user authorization and every result query. Do not supply a borrowed
  connection already inside another transaction. Separate calls have independent
  snapshots; use `report_bundle` when sales, payments and SD must reconcile from
  the same snapshot. Connection isolation/read-only settings reset on pool return.
- Items are aggregated per order before counting orders. Payment allocations are
  aggregated independently and combined with item aggregates in Python; no raw
  item-by-allocation join multiplies totals. Money remains PostgreSQL NUMERIC /
  Python Decimal. Reconciliation difference is item sales minus allocated total;
  equality is an internal arithmetic check, not external payment verification.
- Sales results include Received order count, total item quantity (including
  extra rice), meal quantity (vegetable/non-vegetable meals), snapshot item and
  category breakdowns, payment amounts and reconciliation difference. Items group
  by recorded source offering, name, category and unit price, so changed snapshots
  remain separate. Three item categories and five payment categories include zero
  entries for empty periods; there are no invented payment categories.
- SD includes only the actual `sd` allocation of each Received employee order.
  Per-employee totals/counts use exact employee numbers; per-order details retain
  service date, order ID, name/position/campaign/line-of-business snapshots and SD
  amount. If one employee's snapshots differ between orders, retain each version
  in the details rather than select an arbitrary current name. Equal names never
  merge employees. No live HRMS, employee-directory or catalog join relabels sales.

No payroll execution/settlement, export formatting, report locking/submission,
refund/cancellation accounting, authentication or frontend feature was added.

## Stage 5 authentication and authorization

The owner approved [the session proposal](../../docs/authentication-session-proposal.md).
`AuthService` uses individual accounts and Argon2id (`argon2-cffi==25.1.0`), with
64 MiB memory, three iterations, one lane, random salts and rehash on successful
login when needed. Passwords require at least 8 characters, a nonblank value and
at most 1,024 UTF-8 bytes; passwords are never trimmed. No character-class rule is
imposed. This minimum is for the local demo; longer passwords are recommended for
production. There
are no default accounts, fallback hash algorithms or public registration.
Lookup uses PostgreSQL `lower(btrim(login_name))`, matching the unique index.
Unknown, disabled, malformed-hash and incorrect-password cases share a generic
failure with comparable verification work. Credentials/hashes are never returned
or logged by these modules.

Sessions use 32 random bytes encoded as an opaque cookie; PostgreSQL stores only
their SHA-256 digest. An independent server-stored CSRF token is returned to the
authenticated client for headers, never used as identity. Login creates a new
session and atomically revokes the previous browser session when presented.
Independent browsers remain independent. Validation/logout lock User rows before
session rows and check stored enabled/role state. User locks are sorted when
switching accounts. Sessions expire at 8 hours absolute or 30 minutes idle;
activity cannot extend absolute expiry, move backwards, revive expiry or undo
revocation. Future account/password/role management must atomically revoke affected
sessions; those management operations are not exposed here.

Only these routes were added:

- `POST /auth/login`: JSON with exactly `login_name` and `password`, a trusted
  `Origin`, and `X-ASI-Request: 1`; maximum body 8 KiB. Issues the session cookie.
- `GET /auth/me`: verifies the session and returns user ID/login/display name/role
  and CSRF token; rejects supplied untrusted Origin/cross-site fetch.
- `POST /auth/logout`: trusted `Origin` and `X-CSRF-Token` matching that session;
  commits revocation before clearing the cookie. No GET logout.

Responses use `Cache-Control: no-store`; storage errors return generic 503s.
Login has a bounded per-process guard of five attempts per socket client IP per
minute, at most 1,024 active limiter entries. It is not shared across workers and
does not trust forwarded IP headers. Deployment-wide abuse/proxy controls require
review before live use. Session state itself is shared PostgreSQL state.

`authenticated_actor` and `admin_actor` derive actors only from verified cookies
and enforce Origin/CSRF on unsafe methods. Existing services still check stored
roles: both roles perform routine Pending operations, mark Received and read
operational reports; only Admin reverses Received or imports. Admin account/audit
permissions are preserved without adding account/audit HTTP endpoints. Ordinary
request bodies cannot supply actor IDs or roles. Business endpoints remain absent.

### Explicit configuration

Importing the app does not connect or create accounts. Auth routes return 503
unless explicitly enabled/configured. Set `ASI_AUTH_ENABLED=true`, an explicit
`ASI_DATABASE_URL` (`postgresql+psycopg`), and `ASI_AUTH_ORIGINS` (comma-separated
exact origins, no trailing slash). `ASI_AUTH_MODE=https` is the default. Invalid
enabled configuration fails startup; it never migrates. Apply migrations separately
using authorized access. No credential or environment file was created/modified.

HTTPS mode requires HTTPS requests/origins and uses
`__Host-asi_session; Secure; HttpOnly; SameSite=Lax; Path=/` without Domain.
Explicit `ASI_AUTH_MODE=development` permits HTTP loopback origins only, requires
a loopback socket client and hostname, and uses separate `asi_dev_session` with
HttpOnly/SameSite/Path but without Secure. Host headers never select this profile.
Do not expose it through a remote proxy. Credentialed CORS is not enabled: use a
same-origin client; future cross-origin frontend integration needs explicit
allowlist/preflight configuration. TLS/trusted-proxy setup is not implemented by
this stage, and passing liveness `/health` does not prove authentication readiness.

### One-time local provisioning and cleanup

From the repository root, with an explicitly supplied authorized database URL
outside logs/Git and the schema migrated:

```powershell
$env:PYTHONPATH = 'C:\asi-meal-management\apps\api\src'
.\.venv\Scripts\python.exe -m asi_meal_api.auth_cli bootstrap-admin
.\.venv\Scripts\python.exe -m asi_meal_api.auth_cli cleanup-sessions
```

Bootstrap requires an interactive hidden-input terminal, prompts for the chosen
individual login/display name and password twice, refuses visible-input fallback,
and accepts no credential arguments. A provisioning lock permits only one first
Admin; any existing Admin, including disabled, causes refusal. The account and
explicit local-bootstrap audit commit together. This is not a recovery command;
normal startup/migrations never invoke it.

Schedule cleanup explicitly (recommended hourly); each invocation removes at most
1,000 expired/revoked rows with locks, leaving audits intact. Idle-expired rows may
await absolute expiry for deletion but cannot authenticate. No CLI operation was
run against a real database. Production use still needs reviewed runtime privileges,
TLS/origins, abuse controls and recovery; no production-readiness claim is made.

## Stage 6 protected business API

All `/api/` operations require the real Stage 5 session. Unsafe methods also
require an allowed `Origin` and the session's `X-CSRF-Token`. Actor identity comes
from that session; each service rechecks stored enabled/role state within its own
transaction. Both roles have routine access; CSV imports and Received reversals
are Admin-only. There are no account-management, audit-history,
price-override or historical snapshot-edit endpoints. All API responses use
`Cache-Control: no-store`; cookie and deployment configuration are unchanged.

| Method | Path | Operation |
| --- | --- | --- |
| GET | `/api/employees` | Minimal directory; employee number/name substring search. |
| POST | `/api/employees/import` | Admin-only existing whole-file importer. |
| GET, POST | `/api/visitors` | Search/reuse stable visitor IDs; audited creation with display name only. |
| PATCH, DELETE | `/api/visitors/{visitor_id}` | Rename or delete an unreferenced visitor; the expected name detects stale changes. |
| GET, POST | `/api/dishes` | Search/filter category/active flag; audited creation in an approved category. |
| PATCH, DELETE | `/api/dishes/{dish_id}` | Rename/reclassify a meal dish; delete unused dishes or deactivate those retained by saved menus. |
| GET | `/api/menu-defaults` | Read the current configured Extra Rice category price. |
| POST | `/api/menus` | Configure a new definition from selected dish IDs, optionally assign explicit dates. |
| PUT | `/api/menus/{menu_id}/dates` | Assign that menu to one or multiple explicitly selected dates. |
| GET | `/api/menus/by-date/{service_date}` | Assigned menu and retained offering names/categories/prices. |
| GET | `/api/menus/{menu_id}` | Retained offerings by recorded menu ID; Stage 7B contract gap fix for editing after date reassignment. |
| GET, POST | `/api/orders` | Filter/list or create Pending using the existing order service. |
| GET | `/api/orders/page` | Pending-first register page with a filter-bound listing revision. |
| GET, PATCH | `/api/orders/{order_id}` | Recorded details/allocations or approved Pending edits. |
| POST | `/api/orders/{order_id}/received` | Both roles; expected version required. |
| POST | `/api/orders/{order_id}/reverse-received` | Admin; expected version, predefined reason, checked acknowledgement; nonblank Other explanation. |
| GET | `/api/reports/sales` | Existing sales summary. |
| GET | `/api/reports/payments` | Existing allocation summary. |
| GET | `/api/reports/salary-deduction` | Protected SD amounts and recorded employee snapshots. |
| GET | `/api/reports/bundle` | All three reports in one consistent snapshot. |

Directory/catalog lists use `q` (literal substring, at most 100 characters),
`limit` (default 20, 1–100) and `offset` (0–10,000), with stable ordering. Dish
filters are `category` and `active`. Order filters are inclusive `start`/`end`,
exact text `employee_number` or `visitor_id`, and `status=pending|received`.
Employee outputs contain only number/name/position/campaign/line of business;
leading zeros survive. Visitor reuse means selecting an existing ID; equal names
are not automatically merged or treated as a unique identity. Explicit creation
creates a new visitor; staff can search first. No merge policy is introduced.

The register's `/api/orders/page` returns `{orders, revision}`. The first page
uses offset 0 without a revision; later pages require the returned 64-character
revision and identical filters and page size. Malformed or missing revisions
are rejected; a changed listing returns 409 and requires restarting at page 1.
The fingerprint covers matching order IDs, dates, statuses and versions, and is
calculated in the same repeatable-read transaction as the page. Changes after a
response are detected on the next page request, not pushed to an already displayed
page. The fingerprint scans all matching orders, so very large result sets may
require a future performance review. Legacy `/api/orders` offset pagination
remains available but does not provide this consistency guarantee.

Menu input contains `label`, `dish_ids` (1–100 distinct IDs), and optional
`assignments`. Each assignment contains `service_date` and **required**
`expected_menu_id`: null asserts an unassigned date; an ID asserts its current
assignment. Dates must be distinct (at most 366 per request). Stale assignments
return 409 and the whole operation rolls back. Scheduling serializes absent-row
creation and locks existing dates before the target menu, coordinating with order
creation. Only listed dates change; each actual assignment and new definition
is audited atomically. Configure changed offerings by creating a new definition
and explicitly assigning selected dates; no in-place reused-menu mutation is
exposed. New offerings copy active dishes and locked category default prices;
old offerings and every existing order retain their recorded configuration.
Custom prices and implicit repricing remain disabled.

Both routine roles may rename visitors and meal dishes, or change a meal dish's
vegetable/non-vegetable category. Changes and unused-record deletions are audited
atomically. Existing order and offering snapshots remain unchanged. A visitor
referenced by an order cannot be deleted. A dish referenced by a saved menu is
deactivated instead of physically deleted and no longer appears in the active
catalog; existing menu offerings remain available. Default Extra Rice is not
editable through these meal-dish operations.

The daily-menu client requests `include_default_rice` when creating a new menu.
Within that transaction, the server serializes default-rice provisioning, reuses
the lowest-ID active `extra_rice` dish whose trimmed name matches `Extra Rice`
case-insensitively, or creates and audits that exact dish if none exists. Other
legacy entries are left intact; explicit rice selections are rejected in this
mode. The saved offering snapshots the locked category price. This flag preserves
the existing menu API behavior for other callers; no existing menu is rewritten.

CSV upload is a **raw `text/csv` request body**, not multipart; no filename or
new upload dependency is needed. The adapter reads at most 8 MiB into memory,
rejects other media types (415) and oversized bodies (413) before importing, and
writes no upload file. The existing importer validates the exact ten-column CSV,
encoding and all rows. Completed jobs return 200; recorded failed batches return
422 with import ID, counts, safe file code and at most 100 rejected-record
summaries (`row_number`, field/error codes, `errors_truncated`). Unsupported or
oversized HTTP uploads do not create an import job. Deliberate retries retain the
existing identity-matching behavior. No separate history-browsing permission is
inferred; these diagnostics accompany the Admin's import response only.

Order POST accepts a UUID request key, service date/menu, exactly one customer,
selected offering IDs/quantities and allocations. PATCH requires
`expected_version` and only `quantities`, `remove_line_ids`, `add_items`, and/or
replacement `allocations`. Omitted/null allocations preserve; an empty list
clears while Pending. Existing rules control allocation balance, visitor Finance,
snapshots, retries and atomic audits. Monetary JSON input must use exact decimal
strings (recommended) or integers; binary floating-point input is rejected.
Money responses are decimal strings. Inputs forbid unknown fields, actor/role,
prices and snapshots. Received edits conflict until Admin reversal. The future
checkbox must use the display name from `/auth/me`; only the checked boolean is
submitted, with actor identity independently verified on the server.

Report query `mode` is required: `daily`/`weekly` require `day`; `monthly`
requires `year` and `month`; `custom` requires `start` and `end`. Extra period
selectors are rejected. Existing service-date/Philippine operational boundaries,
Received-only inclusion, Decimal arithmetic and repeatable-read aggregation are
unchanged; no report math is duplicated in handlers.

Errors are 401 invalid/missing session, 403 forbidden role/Origin/CSRF, 404 absent
resource, 409 stale version/date assignment or incompatible current state, 422
invalid input/business consistency, and generic 503 storage unavailability.
Validation errors never echo submitted personal values or arbitrary field keys;
database exception text is not returned. No schema or migration change was needed.
Operational import recovery/retention, deployment safeguards and the previously
deferred business policies remain outside this stage; no production-readiness
claim is made.

Stage 7B adds only the authenticated menu-by-ID read needed by Pending editing;
date lookup alone cannot recover the recorded menu after reassignment. It reuses
the existing menu serializer and stored-actor authorization, returns 404 if absent,
and introduces no menu writes, schema change or modification to the PATCH contract.

## Verification

Local recovery of an existing active Super Admin uses the interactive
`recover-super-admin` CLI described in the [local runbook](../../docs/local-demo-runbook.md).
It requires independent verification of the database, local administrative
access, self-attested operator attribution, a nonsecret reason, explicit
confirmation and hidden temporary-password input. It atomically requires a
password change, revokes sessions and records a safe audit event. It is not an
HTTP endpoint, an account-creation mechanism, or a substitute for protected
backups and independently verified restores.

From the project root using the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest apps/api/tests -c apps/api/pyproject.toml -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest apps/api/tests -c apps/api/pyproject.toml -p no:cacheprovider --postgres
```

The first command skips PostgreSQL tests explicitly. `--postgres` accepts no
external database URL: the fixture creates a random, labeled PostgreSQL 17
container with generated in-memory test credentials, loopback-only random port,
and tmpfs storage. Before connecting, it verifies the exact created ID/name,
labels, image, absence of binds/volumes/Compose ownership, and tmpfs settings.
After connecting it checks database identity, server major version and empty
schema, then migrates. It removes only its own exact container ID in `finally`;
it never mounts or deletes the application's `postgres_data` volume.

Integration tests cover migrations/drift, approved reference data, mapper
relationships, constraints, deferred totals, immutable snapshots, reasons,
transaction rollback, and two-connection lock conflicts. All fixture data is
synthetic and separate from migration seed data. Low-level receipt fixture
writes are not an implemented or authenticated application workflow.

Stage 2 tests additionally check actual saved state/history for service permissions,
creation/retries, edits, Received/reversal/re-marking, reasons/acknowledgement,
failure rollback, and stale/concurrent writes. Concurrency tests use fresh random
schemas migrated with the unchanged revisions inside that same verified disposable
database, so they can commit independently without contaminating Stage 1 checks.
They verify an actual PostgreSQL lock wait before releasing the first writer and
drop only their own temporary schema. All test resources remain disposable.

Stage 3B tests use generated CSV bytes/streams only. They verify employee effects,
unchanged snapshots, metadata/outcomes, privacy-safe diagnostics, role denial,
rollback/failure-history behavior, deliberate retries and actual serialization
lock waits. They never open the workspace's real HRMS export.

Stage 4 tests use committed synthetic orders in the same disposable-schema
fixture. They check Received-only totals, item quantities, all five allocation
categories/splits, SD identity and snapshots, calendar boundaries, exact arithmetic,
role denial, read-only/isolation settings and connection reset. Concurrent tests
pause a report between aggregates while an order is marked, reversed or corrected;
the in-flight bundle retains one snapshot and the next call sees the new state.

Stage 5 tests use randomly generated synthetic passwords and real Argon2id. They
cover migration/drift/data retention, generic failures, rehash, cookie profiles,
CSRF/actor dependencies, expiry/rotation/revocation, cleanup, concurrent logout
and first-Admin provisioning, rollback and hidden-input CLI safeguards.

Stage 6 tests use real login cookies and CSRF tokens with the same verified
disposable PostgreSQL environment. They cover the exact route surface, anonymous
and disabled-account denial, both-role routine operations, Admin-only import and
reversal, every mutation's Origin/CSRF enforcement, leading-zero search/identity,
upload validation/privacy, visitor reuse/audit, menu scheduling/conflicts/prices,
historical provenance, split edits/transitions/stale versions, report modes and
totals, bounded pagination, safe errors and rollback on failed audit insertion.

Implementation references: [typed SQLAlchemy mappings](https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html),
[Alembic autogeneration/review](https://alembic.sqlalchemy.org/en/latest/autogenerate.html),
and [PostgreSQL 17 constraint triggers](https://www.postgresql.org/docs/17/sql-createtrigger.html).
