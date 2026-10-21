# ASI Meal web interface

Stage 7A provides real login/session/logout, an authenticated application shell,
employee/visitor selection and visitor creation, Pending order entry, date/status
order lists, recorded details/allocations, Received marking and Admin reversal.
The Visitors navigation section identifies a screen deferred beyond this stage;
directory selection works within order entry.
Stage 7B adds permitted Pending item/quantity/allocation editing for both roles.
Stage 8 replaces Menu with dish catalog, new-definition review, saved-menu
inspection and explicit multi-date scheduling for both roles.
Stage 9 adds a paged employee directory for both roles and an Admin-only HRMS CSV
import panel.
Stage 10 adds operational sales, payment allocation and Salary Deduction reports.

## Operational reports (Stage 10)

Both roles can request `GET /api/reports/bundle` for a daily date, a week
containing a chosen date (Monday through Sunday), a calendar month or an inclusive
custom range. The initial date uses Asia/Manila regardless of browser timezone.
The displayed start and end come from the backend. Refresh requests a new bundle;
all three sections in each response share the same database snapshot.

Only currently Received orders contribute. Sales categories and item snapshots
are shown separately from payment allocations; split payments use the backend's
category totals. Salary Deduction shows backend employee totals and each order's
recorded name and organizational snapshots, which may differ over time. Report
amounts remain decimal strings and are formatted without floating-point arithmetic.
SD allocation is not proof of payroll completion. Reports reflect current status;
period locking, payroll processing and exports remain outside this stage.
The existing API returns the complete report and has no report pagination.

## Employee directory and import (Stage 9)

Search the directory by employee number or name; results use `GET /api/employees`
in pages of 20. Employee numbers remain text, including leading zeros. The API
does not provide a total count; a full page offers Next and a subsequent page may
be empty. Search can be refined at the backend's maximum offset.

Admins may explicitly submit a local `.csv` file up to 8 MiB using raw
`text/csv` to `POST /api/employees/import`. The existing same-origin cookie,
CSRF and server authorization apply. File contents are not saved in browser
storage. A successful import refreshes the directory; a rejected batch displays
safe counts and record/field codes, with no partial employee updates. A network
or server failure can leave the outcome uncertain; review before a deliberate
retry. The backend owns CSV validation and import history. No import-history
listing endpoint is currently exposed.

## Same-origin local development

Use the existing frontend dependencies and a compatible Node.js runtime (the
project API/web images use Python 3.13 / Node.js 24). Do not change the system Node
installation. From `apps/web`, run `npm run dev -- --hostname 127.0.0.1` and open
**http://127.0.0.1:3000**. Local Cardo/Open Sans packages are already installed;
no remote font or cloud service is used.

Next.js rewrites `/auth/*` and `/api/*` to `ASI_API_ORIGIN`, a server-only HTTP(S)
origin, default **http://127.0.0.1:8000**. There is no browser-facing API URL,
credentialed CORS workaround, or custom authentication proxy. For a different API
port, set the non-secret `ASI_API_ORIGIN` before starting development. For a
production build, set it **before `npm run build`** because Next.js records
rewrites in its build output. Do not put credentials in this URL.

Start the separately configured FastAPI service on loopback with its existing
migrated, authorized database and an individually provisioned account, following
[backend configuration](../api/DATABASE.md). Relevant development settings:

```powershell
$env:ASI_AUTH_ENABLED = 'true'
$env:ASI_AUTH_MODE = 'development'
$env:ASI_AUTH_ORIGINS = 'http://127.0.0.1:3000'
# Supply ASI_DATABASE_URL privately, using the existing PostgreSQL configuration.
# From the repository root, in the API terminal:
$env:PYTHONPATH = 'C:\asi-meal-management\apps\api\src'
.\.venv\Scripts\python.exe -m uvicorn asi_meal_api.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

The explicit development profile accepts only loopback clients/hosts and uses
`asi_dev_session; HttpOnly; SameSite=Lax; Path=/`. Always browse through Next.js;
do not mix localhost and 127.0.0.1 origins. Browser mutations supply their actual
Origin; the frontend sends the session CSRF header, and login also sends
`X-ASI-Request: 1`. Rewrites preserve these headers and Set-Cookie. Passwords and
session tokens are never placed in local/session storage; the independent CSRF
value exists only in React memory. Session checks run on entry and window focus;
a 401 clears the protected interface and requires sign-in again. Logout revokes
the server session before clearing the UI. Backend role checks remain authoritative.

**This is not a production deployment.** The unchanged Compose setup does not yet
configure authenticated API access. Do not point a remote Compose web container
at the API's loopback-only development profile. An eventual HTTPS deployment must
keep the secure cookie profile and ensure FastAPI sees HTTPS through an explicitly
reviewed secure upstream/trusted TLS proxy; this stage does not configure TLS,
trusted proxy boundaries, production credentials or database access. Never disable
Origin, CSRF, HttpOnly or HTTPS checks to resolve an integration error.

## Entry and correction behavior

The service-date picker calls the real assigned-menu lookup. An unassigned date
shows a clear message; the API currently has no assigned-date directory endpoint.
Item prices and saved snapshots come from the server. Entry previews calculate
integer centavos only; submitted items contain offering IDs/quantities, with no
prices, snapshots, actors or roles. Employee numbers remain text. Visitors use
Finance only. Split entries show allocated amount and difference; Pending may be
incomplete, but Received requires balanced positive allocations.

Creation uses one UUID per submitted payload. An uncertain network/storage outcome
retains that exact payload for **Retry same order**; automatic retries never create
a new identity. Review the order list before abandoning an uncertain submission.
Drafts and retry keys are memory-only and are lost on navigation/reload/sign-out.
Saved success opens recorded details and selects that order's service date.

Order lists are paged in groups of 20. Displayed Received/Pending subtotals are
explicitly **for the current page only**, not full operational reports. Status
changes use the displayed version, then reload details/list/totals. Conflicts never
automatically resubmit with a newer version. Admin reversal requires one of the
five current predefined reasons, a trimmed explanation for Other and a checked
confirmation containing the authenticated display name. Only the reason,
explanation, acknowledgement and expected version are submitted. Assistant Admin
reversal controls are hidden and the server still denies that operation.

## Pending order editing (Stage 7B)

Open a Pending order's details and choose **Edit Pending order**. The editor
copies the saved lines and allocations into a separate in-memory draft. Cancel
discards that draft without an API mutation. Received orders have no Edit action;
the existing Admin reversal procedure is unchanged.

Change quantities, search the recorded menu, add offerings, explicitly replace
lines, or remove lines while retaining at least one. Existing quantities use
the original line IDs and recorded price/category snapshots. Replacement sends
an atomic removal plus new offering selection. New/replaced lines are previewed
from the recorded menu and receive authoritative snapshots from the server.
No customer, service date, recorded menu, price, actor or audit fields are editable.

The former API only looked up menus by service date, which is insufficient after
date reassignment. The narrow contract fix adds authenticated
`GET /api/menus/{menu_id}` using the existing serializer and service authorization.
The editor always requests the saved order's menu ID; it never substitutes the
date's latest menu. No schema/migration or PATCH-contract changes were required.

Single/split allocations prepopulate the saved amounts. All five approved
categories are available to employee orders; visitor orders expose Finance only.
Blank removes an allocation; entered amounts must be positive exact centavos.
Switching to a single method saves only the displayed category/amount. Incomplete
or empty Pending allocations are allowed; Received still requires equality.
Item total, allocated total and difference update with field-level validation.

Save sends only `expected_version`, changed line quantities, removed IDs, added
offering IDs/quantities and replacement allocations through the existing PATCH
endpoint and session/CSRF client. Repeated submissions are disabled while saving.
Success re-reads authoritative details/version and refreshes the register/totals.
Stale-version or Received conflicts block the draft until **Reload latest order**;
no newer version is silently adopted or automatically resubmitted. Uncertain
network/storage outcomes also require a reload. Expired sessions clear the
authenticated shell; forbidden/missing records and safe validation errors remain
actionable. Backend authorization and Pending-only guards remain authoritative.

## Menu and dish management (Stage 8)

The Menu section uses the existing authenticated contracts without backend or
schema changes:

| Contract | Use |
| --- | --- |
| `GET /api/dishes` | Search name/category/active status; bounded paginated catalog reads. |
| `POST /api/dishes` | Create a reusable name/category and immediately select its returned identity. |
| `POST /api/menus` | Create a separate new definition using optional label and distinct dish IDs. |
| `GET /api/menus/{menu_id}` | Inspect saved offerings, categories and actual configured prices. |
| `GET /api/menus/by-date/{service_date}` | Inspect a date's existing assignment before replacement. |
| `PUT /api/menus/{menu_id}/dates` | Assign explicit dates with each reviewed `expected_menu_id`. |

Search results are alphabetically ordered with ID tie-breaking, not ranked by
sales. Up to 1,000 matching records are retrieved in pages of 100 and displayed
20 at a time; refine search when truncated. **Capability gap:** the API exposes
no distinct-menu-definition selection counts, so popularity ordering is deferred;
no scores are invented. Inactive dishes are shown but cannot be newly selected,
matching the backend rule. Duplicate IDs are prevented and a menu selects at most
100 dishes. Names alone are not treated as unique identities.

Selected dishes form a review table before **Save new menu**. **Price-preview
gap:** current category defaults have no read endpoint. The draft therefore
clearly labels the approved starting values (Vegetable 50, Non-vegetable 75,
Extra Rice 15) as **reference prices**. Only dish IDs and a label are submitted;
actual prices/categories come from the backend, can differ from these references,
and are shown on the saved-menu table before any scheduling. No arbitrary prices
are sent. Current defaults cannot be verified before menu creation with the
available API; this limitation is visible in the interface.

Menus can be loaded by ID or assigned date; there is no menu index endpoint.
Save always creates a new definition; no shared-menu offering is changed in place.
For different offerings, create a new definition and explicitly assign only the
desired dates. No stock/quantity, deletion, reclassification or price-override
controls are introduced. Order-entry quantities remain in the order workflow.

Add explicit dates across a week or month, then **Review date assignments**.
Only a 404 is treated as unassigned; network/permission errors cannot become an
unassigned assumption. Each date replacing another menu requires its own checked
confirmation naming the old and target IDs. Changing dates or the target menu
invalidates the review/confirmation. The backend receives the reviewed old IDs
(null for unassigned), so a race returns 409 and requires a new review. No stale
request automatically overwrites another assignment. Success reloads assignments;
already-assigned dates do not require another write. Original orders and snapshots
are preserved, and unselected reused-menu dates are untouched.

Dish creation, menu saving and scheduling disable repeated submissions. Successful
menu creation disables repeat saving of the same draft. Uncertain creation
outcomes are not automatically retried: dish/menu POST has no request key, and
there is no menu index for recovering an unknown creation ID. Review the outcome
before deliberately starting another definition. Uncertain scheduling requires
fresh date inspection. API/session errors use the existing safe client and a 401
clears the authenticated shell. All drafts remain memory-only.

## Verification commands

From `apps/web`, using Node.js 24:

```powershell
npm run lint
npm test
node node_modules/typescript/bin/tsc --noEmit --incremental false
npm run build
```

Focused Node tests cover exact totals, split difference, safe payloads/text IDs,
visitor Finance, reversal visibility/acknowledgement, cookie-aware requests, CSRF,
login/logout and privacy-safe API/conflict errors. They mock transport only and
are not a claim of browser end-to-end verification.
Pending-edit tests also cover prepopulation, snapshots, add/replace/remove,
single/split and visitor Finance, incomplete amounts, Cancel draft isolation,
Received/role visibility, exact totals, successful PATCH/read-back and stale or
expired-session rejection without retries. TypeScript permits explicit `.ts`
imports so the existing Node.js test runner can load the shared draft functions;
no test dependency was added.
Stage 8 tests cover paginated/alphabetical dish search, creation/selection,
duplicate IDs, new-menu payloads and backend prices, multi-date review, required
replacement confirmation, PUT/CSRF, stale/session errors and no implicit history
mutation. No popularity or production records are used as fixtures.

The opt-in real Next.js/FastAPI HTTP integration test starts its own loopback
servers using the local Node executable (`ASI_TEST_NODE` can select an isolated
Node path). It uses the existing verified disposable PostgreSQL harness, real
sessions and synthetic data only. From the repository root:

```powershell
$env:ASI_WEB_INTEGRATION = 'true'
.\.venv\Scripts\python.exe -m pytest apps/api/tests -c apps/api/pyproject.toml -p no:cacheprovider --postgres -q
```

It checks actual rewrite forwarding, HttpOnly cookie issuance/reuse, session
lookup, Origin/CSRF rejection, visitor and order creation, Received/version
conflicts, stored-role reversal denial, Admin reversal and logout.
The Stage 7B extension verifies both-role Pending PATCH requests through the real
proxy, CSRF rejection, quantity/add/replace/remove and split allocations, original
snapshots after source-price changes, recorded-menu lookup after date reassignment,
visitor Finance-only and incomplete allocations, stale versions and Received-edit
rejection. Stage 8 additionally verifies both-role dish/menu creation with updated
configured prices, menu/date inspection, multi-date reuse across months, CSRF,
replacement conflicts, unchanged other dates and preserved sale-time snapshots.
It does not
connect to an existing project/HRMS database or provision a real account. Frontend
lint/build can also run inside the existing `infra-web` Node.js 24 image using a
read-only source mount and temporary container filesystem; no dependencies or
Node installation need to change.
