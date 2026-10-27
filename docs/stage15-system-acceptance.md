# Stage 15.1 — System business-workflow acceptance

Date: 2026-10-27. Target for non-mutating live checks:
`https://192.168.45.145:43873/`, Compose project `asi-meal-dev`.

## Result and evidence boundaries

**Automated acceptance passed: 274 backend tests and 105 frontend tests, with
zero failures or skips in the final runs.** A real HTTP integration test ran
Next.js and FastAPI against disposable PostgreSQL and generated/reopened actual
four-sheet workbooks from the resulting API report data. This is an automated
HTTP-to-database-to-XLSX workflow, not a browser-driven order-entry test.

No application business logic or export formatting changed. The only code change
is to an existing integration test: correct its outdated visitor receipt
expectation and extend its coverage. The test previously expected HTTP 422 for
an empty visitor Finance allocation; the implemented, owner-approved receipt
workflow fills Finance to the recorded item total in the receipt transaction.
The revised test verifies that behavior, a stale retry, and reversal permissions.

Live browser evidence in this stage is limited to the existing authenticated
Reports page, including its empty-period sales/payment/SD state at 390, 768 and
1440px. Browser control returned `element 324 has no cached bounds`; one fresh
window observation showed another application over the preview while the desktop
was in use. Further input was stopped. Period changes, actual downloads, login,
logout and business mutations were **not** exercised in the live browser during
this stage. Prior-stage browser/Excel acceptance is not counted as a new pass.

All synthetic business writes, migrations, credential fixtures and concurrency
experiments ran only inside newly created disposable PostgreSQL 17 containers.
No development accounts, employees, menus, visitors, orders, credentials or
financial records were changed. No development service was rebuilt/restarted.

## Supported behavior established by inspection

Sources: root/frontend engineering instructions; root README; API database and
authentication documentation; business requirements; report data contract;
`orders.py`, `business_services.py`, `reports.py`, `auth.py`, `auth_http.py`,
user management/activity adapters and services; schema models/constraints;
frontend report/Excel implementation and tests; `infra/dev` configuration and
runbook. Older stage descriptions in the README and business requirements are
not reliable descriptions of the current implementation.

- All three enabled operational roles can place orders, manage routine menus,
  dishes/visitors, mark Received and view reports. Admin/Super Admin can reverse
  Received and import employees. Only Super Admin can manage ordinary users and
  read Activity Logs. There is no implemented read-only business role.
- Pending employee allocations may be incomplete or empty. Received requires
  positive, exact balanced allocations. Invalid amounts/categories are rejected.
  Visitors accept Finance only; receipt automatically balances Finance to their
  recorded item total. There is no external payment/Finance approval state.
- New daily menu saves can include canonical Extra Rice automatically at its
  configured price. Draft edits do not publish to Orders. Saved offerings and
  order snapshots preserve historical prices and identities.
- Reporting uses inclusive Philippine operational service dates, Monday–Sunday
  weeks and calendar months. Only currently Received orders contribute; reversal
  excludes an order and re-receipt restores it once. SD describes allocations,
  not completed payroll.
- Backend money uses Decimal/NUMERIC and centavos; JSON money is a decimal
  string. Employee numbers remain text. Full export details are opt-in on the
  existing report bundle; employee search does not filter the export.

## Acceptance scenarios and outcomes

| Area | Result and evidence |
| --- | --- |
| Employee search/import | PASS, PostgreSQL/HTTP/proxy and frontend tests. Leading-zero identifiers, equal names, optional-field retention, invalid CSVs, missing employees and permission failures are covered. The real proxy imports/searches synthetic employee `000042`. |
| Date menus and Extra Rice | PASS, `test_default_rice`, `test_stage14e`, `test_business_http`, real proxy. Zero/one/multiple legacy rice entries, concurrent canonical provisioning, configured prices, saved snapshots, stale assignments and atomic rollback are covered. New acceptance menu has exactly one Extra Rice offering. |
| Employee order lifecycle | PASS, `test_orders`, `test_business_http`, real proxy. Create Pending, edit quantities/add/remove lines, mark Received, Admin reversal/re-receipt, stale versions and preserved identity/date/menu/price snapshots. |
| Duplicate processing | PASS. UUID request-key retry returns the same order; differing payload conflicts. Concurrent creation and competing receipt/edit/reversal writers are tested. Current-version receipt retry adds no event; stale receipt returns 409. |
| Visitors | PASS. HTTP/proxy tests create/search a synthetic visitor, reject Cash edits, clear Pending allocations, mark Received with automatic Finance, and verify exact Finance amount. Report/export tests exclude visitors from employee SD. |
| Five payment methods/splits | PASS. Cash, GCash, SD, Incentive and Finance participate in the new real-proxy case; exact amounts and Received-only reporting reconcile. Incomplete employee Pending order cannot be marked Received. |
| Financial input boundaries | PASS, schema/service/HTTP tests: float/nonfinite/fractional-centavo/negative amounts, overflow, invalid quantities/categories and over/under-allocation at receipt. Zero-price schema support is not a policy approving zero-total receipts; these cannot satisfy the present positive-allocation receipt rule. |
| Historical changes | PASS. Import, catalog/menu and category-price changes do not rewrite recorded customer/item/category/price values; newly added lines use the order's recorded-menu offerings. Separate snapshot tests verify campaign changes and centavos. |
| Reports/SD | PASS, `test_reports`, `test_report_export`. Daily/weekly/monthly/custom, leap/calendar boundaries, empty periods, per-date totals, current reversals, exact SD/campaign grouping, visitor exclusion and concurrent repeatable-read snapshots. |
| Complete export scope | PASS. A 105-order fixture is returned completely without pagination/N+1 growth. Search/limit/offset cannot restrict export data. The documented 3,660-date resource limit returns an explicit error. |
| Excel integration | PASS, real proxy report bundle -> existing generator -> actual XLSX bytes -> ExcelJS/JSZip reopening, for all four period modes. Exactly four approved sheets, four chart parts, numeric dashboard total, leading-zero text ID and print areas verified. Existing frontend tests additionally verify formulas/cached results, chart relationships/source ranges, 7/8 and 31/32 layouts, unsafe-text handling and empty reports. |
| Reconciliation failure | PASS. Corrupted sales/payment/SD summaries fail closed; HTTP 409 exposes a safe code and no partial export payload. Frontend tests verify error feedback and cancellation after period changes. |
| Authentication/session/CSRF | PASS, PostgreSQL and real HTTP proxy. Argon2id, generic credential failures, disabled users, idle/absolute expiry, cookie profiles, logout/re-login, session rotation, CSRF token pairing, trusted Origin and rate limit. |
| Users/role boundaries | PASS. All three report roles, routine Admin/Assistant access, denied Assistant reversal/import, denied ordinary user/activity API access; Super Admin-only user management, protected Super Admin accounts, optimistic concurrency, mandatory first password change and session revocation on reset/role/status changes. |
| Audit/atomicity | PASS. Order creation/edits/receipts/reversals, visitor/menu/import/user events, actor attribution, reason/acknowledgement rules, immutable receipt/audit history, transaction rollback on audit/storage failures and allowlisted Activity Log output. New proxy case verifies attributed order-created/receipt events via Activity API. |
| Frontend workflows/errors | PASS as component/library regression tests, not live full-browser acceptance: navigation visibility/drawer focus, order detail/edit guards, menu drafts, customer search/tab keys, report controls/download behavior, Users dialogs and Activity filters/loading/error states. |

## Exact financial evidence

The new proxy scenario creates a saved menu using configured Vegetable `50.01`,
Non-vegetable `75.00` and Extra Rice `15.00` prices in disposable data only.

| Synthetic contribution | Amount |
| --- | ---: |
| Received employee: 3 × 50.01 + 75.00 + 15.00 | 240.03 |
| Received visitor: 1 × 50.01, Finance auto-filled | 50.01 |
| Recognized sales, item sales and total allocations | **290.04** |
| Cash | 10.01 |
| GCash | 20.02 |
| Salary Deduction | 100.00 |
| Incentive | 40.00 |
| Finance (employee 70.00 + visitor 50.01) | 120.01 |
| Reconciliation difference | **0.00** |
| Additional incomplete Pending order excluded from sales | 240.03 |

All four period responses contain exactly the two Received order identities and
one SD employee (`000042`); generated workbook dashboard cache is 290.04.
The custom period spans 32 days and exercises the longer SD register. Separate
tests verify recorded-campaign SD totals and per-date reconciliation.

The pre-existing proxy lifecycle also verifies 295.00 sales = Cash 65.00 +
GCash 200.00 + SD 30.00, reversal down to 245.00/SD 0.00, and re-receipt back to
295.00/SD 30.00 without duplicate recognition. Snapshot/centavo export tests
preserve 150.03 from three 50.01 items independently of later 60.02 offerings.

## Security and operational inspection

Read-only Docker inspection confirmed:

- `asi-meal-dev-web-1`: Caddy gateway, bound to loopback and
  `192.168.45.145:43873` only.
- `asi-meal-dev-frontend-1`, `asi-meal-dev-api-1`, `asi-meal-dev-db-1`:
  all reported healthy. API/database have no host-published ports.
- Database persistence: named volume `asi-meal-dev_dev_postgres` mounted at
  `/var/lib/postgresql/data`. No database connection was opened for this review.
- `docker compose -f infra/dev/compose.yaml config --quiet` passed.
  Source configuration names project `asi-meal-dev`, uses an internal database
  network and `unless-stopped` restart policies. API/frontend run as non-root
  container users, but use development reload servers.
- Private `.env` files are Git-ignored and are not tracked. Secret values were
  not printed. Compose requires explicit credentials/origins. TLS is terminated
  by Caddy; existing secure cookies, CSRF and trusted proxy/origin rules remain.

HTTPS checks using normal validation against the existing public development CA:

| Request | Result |
| --- | --- |
| `/` | 200 |
| `/health` through gateway | 200 |
| Unauthenticated `/auth/me` | 401 |
| Unauthenticated `/api/users` | 401 |
| `/docs`, `/openapi.json` through gateway | 404 |
| Login with untrusted Origin | 403 |

`/health` is liveness only; its handler does not query PostgreSQL. Existing
authenticated Reports rendering is additional read-path evidence, not proof of
every current database operation. No certificate validation bypass was used.

Additional sanitized Docker ownership/restart/log-driver and recent error-count
inspection was **not executed**: automatic approval review failed due to a usage
limit, not a determination that the action was unsafe. Recent runtime log errors,
effective Docker log rotation and final post-test disposable-container inventory
therefore remain unverified. The completed pytest harness has a finally block
that disposes its engine and removes only its own exact temporary container ID;
both completed runs exited normally, but no separate final Docker inventory was
obtained. No attempt was made to bypass approval review.

## Defects, gaps and outstanding decisions

| Priority | Finding / disposition |
| --- | --- |
| P0 | None demonstrated by the exercised scenarios. This is not a general production-readiness certification. |
| P1 operational gate | Current development backup/restore readiness is not newly proven. `infra/dev/README.md` records a verified initial cutover/restore and persistence check, but a current-stack scheduled backup, retention, off-host protection, restore drill and recovery objectives remain to be established in the separately controlled recovery stage. No backup/restore was executed here. |
| P1 operational gate | Compose uses the PostgreSQL initialization user for the API and defines no separate least-privilege runtime role. Effective database grants were not queried. Verify/isolate runtime privileges before production; do not assume audit triggers protect against a database owner. Requires separate deployment approval. |
| P2 fixed | Real proxy visitor receipt expectation was stale. Updated to assert automatic Finance balancing, exact returned allocation and preserved concurrency/permission guards. No financial behavior changed. |
| P2 | Root README says initial foundation/no business implementation and advertises different testing/UI tooling. Some business/API documentation retains superseded stage descriptions. Consolidate an authoritative current operations/architecture guide in a documentation task. |
| P2 | Python requirements are mostly unpinned; Docker uses development reload commands. Reproducible production dependency/deployment review remains separate; no upgrades or infrastructure changes made. |
| Unverified | Effective runtime log retention/error contents, current backup age, remote-device firewall reachability, performance at large production volumes and production browser/account operation. |

No new financial policy was introduced. Empty/incomplete employee allocations
are valid **while Pending**, as existing tests and implementation specify; only
receipt rejects them. Visitors are automatically Finance-balanced on receipt.
Zero-total receipt policy, payroll execution/cutoffs and production recovery
objectives require owner decisions if those capabilities are later requested.

## Execution record

Final backend command (project root; a unique ignored temp path is used each run):

```powershell
$env:ASI_WEB_INTEGRATION = 'true'
$acceptTemp = Join-Path (Get-Location) ('exports\stage15-pytest-' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -m pytest apps/api/tests --postgres --basetemp $acceptTemp -q --tb=short -ra
```

The harness verifies fresh PostgreSQL 17 identity, random loopback binding,
temporary storage and absence of Compose volumes before connecting. Existing
test migrations apply only there. Real Next/API servers bind random loopback
ports and are stopped by their test; no official development listener is used.

| Check | Final result |
| --- | --- |
| Full backend suite, including real Next proxy and API-to-XLSX extension | **274 passed**, 65.20 seconds, zero skipped |
| Focused proxy + generator-contract regression check | **5 passed**, 8.78 seconds |
| `npm.cmd test` in `apps/web` | **105 passed**, zero skipped |
| `npm.cmd run lint` | Passed |
| `node node_modules/typescript/bin/tsc --noEmit --incremental false` | Passed |
| `npm.cmd run build` | Passed, Next.js 16.4.2 |
| `.\.venv\Scripts\python.exe -m compileall -q apps/api/src apps/api/tests` | Passed |
| `.\.venv\Scripts\python.exe infra/dev/verify.py` | Passed, statuses above |
| `git diff --check` | Passed; Git emits an informational LF-to-CRLF notice for the modified test |

Earlier attempts are not hidden: the initial sandboxed run could not start
Docker (39 passed/235 setup errors); the authorized first full run yielded
272 passed, one stale visitor assertion failure and one Windows pytest-temp
permission setup error. Correcting the expectation and selecting a fresh
workspace-local temp directory resolved both; the final full suite above passed.
Existing Node module-type warnings are informational. No configured Python lint
command was found; syntax and backend test validation were run.

## Not exercised / acceptance limitations

- No live browser create/edit/receive/reverse/delete/import/user mutation was
  attempted. Those require separately approved live writes or a disposable
  browser environment; automated HTTP/component coverage is identified above.
- No new Microsoft Excel GUI recalculation, save/reopen or Print Preview check.
  Workbooks were generated/reopened programmatically; Excel rendering acceptance
  remains the evidence of the completed prior milestone, not a new Stage 15 run.
- No live-browser full-period download or employee-search interaction was
  completed. Real API period retrieval, workbook generation and frontend scope/
  download error handling passed automated tests.
- No live restore, failure/restart drill, credential change, volume deletion or
  persistent-data digest/count scan was performed. Services were left running.

## Exact changes

1. `apps/api/tests/test_web_integration.py`: correct visitor expectation and add
   exact five-method, Pending exclusion, idempotency, attributed audit and
   real API-bundle-to-four-sheet-workbook acceptance assertions.
2. `docs/stage15-system-acceptance.md`: this report.

No application source, schema, dependency, financial calculation, workbook
formatting or deployment configuration changed. No commit or push. Stage 15.1
ends here; production deployment and Stage 15.2 were not started.
