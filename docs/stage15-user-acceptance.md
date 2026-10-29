# Stage 15.4 — Final User Acceptance Testing

Date: 2026-10-28 (Asia/Singapore)  
Target: `https://192.168.45.145:43873/` (`asi-meal-dev`)

## Assessment

**CONDITIONAL — no application defect was confirmed, but this UAT cannot be
closed until the remaining browser checklist is performed.**

This is not a newly confirmed application-business defect. The initial UAT
attempt could not reach the environment. During the continuation, the owner
confirmed that the application loads and normal login works after the gateway
mapping was restored; a fresh TCP probe from this session also reached
`192.168.45.145:43873`. The automation session, however, has no usable browser
bridge and its restricted Windows TLS client cannot acquire Schannel credentials
to independently make an HTTPS request. Consequently, no live browser workflow
can honestly be marked as passed by this UAT session. No development data,
containers, accounts, menus, visitors, or orders were changed.

The latest non-live evidence remains favourable: the documented Stage 15.1
disposable PostgreSQL/HTTP acceptance suite passed its full workflow coverage.
That evidence is recorded below as **automated evidence**, not substituted for
manual UAT.

## UAT checklist

| Scenario | Result | Evidence and scope |
| --- | --- | --- |
| Employee order creation | NOT TESTED | Live write testing is prohibited against development data. Stage 15.1 automated PostgreSQL/HTTP coverage verifies employee selection, dated-menu offerings, quantities, authoritative prices, idempotency and snapshots. |
| Visitor order creation | NOT TESTED | Live write testing is prohibited. Stage 15.1 automated coverage verifies visitor creation/order identity and Finance-only receipt balancing. |
| Payment allocation | NOT TESTED | No live writes. Automated coverage verifies five methods, splits, exact balancing at receipt and incomplete Pending handling. |
| Receipt processing | NOT TESTED | No live receipt/reversal was attempted. Automated coverage verifies Received, reversal/re-receipt, roles, audit and stale-version safeguards. |
| Order management | NOT TESTED | No browser-control session was available to inspect an authenticated Orders workspace. Component coverage exists for searching, details, edit guards and responsive controls. |
| Salary Deduction | NOT TESTED | No live report could be opened. Automated evidence verifies nonzero SD inclusion, campaigns, snapshots and Received-only recognition. |
| Reports and Excel export | NOT TESTED | The owner restored the gateway, but this session could not drive an authenticated browser or make a usable TLS HTTP request. Automated coverage verifies all four period modes, complete export scope, four sheets, exact totals, charts and safe reconciliation failure. |
| Users and role permissions | NOT TESTED | No live login/session. Automated coverage verifies role boundaries, user management restrictions, password-change requirements and session revocation. |
| Activity Logs | NOT TESTED | No live Super Admin session. Automated coverage verifies redaction, filters, cursor navigation and Super Admin-only access. |
| Mobile usability (390px) | NOT TESTED | Browser automation was unavailable. Existing component tests cover touch targets, drawer behavior and responsive structures; this is not browser acceptance. |
| Authentication and logout | NOT TESTED | No live login/logout was attempted. Automated authentication tests cover Argon2id, CSRF, Origin checks, expiry, rotation, disabled accounts and logout. |
| Development service reachability | PASS (owner-confirmed, transport verified) | Owner confirmed the application loads and normal login works after gateway restoration. A fresh `Test-NetConnection` probe reached `192.168.45.145:43873`. Independent HTTP status validation was blocked by the restricted test session’s Schannel failure; this is not treated as an application failure. |

## Automated versus browser evidence

### Fresh checks in this UAT run

| Check | Result |
| --- | --- |
| Frontend tests (`npm.cmd test`) | PASS — 105 passed, 0 failed, 0 skipped |
| ESLint (`npm.cmd run lint`) | PASS |
| TypeScript (`tsc --noEmit --incremental false`) | PASS |
| Production build (`npm.cmd run build`) | PASS — Next.js 16.4.2 |
| Focused backend workflow collection | PASS — 181 tests collected across orders, HTTP workflows, reports, export, auth and activity coverage |
| Python compilation (`compileall`) | PASS |

The backend tests were deliberately **not executed** in this UAT run because
their established isolated-PostgreSQL harness requires Docker, and Docker
daemon access was denied to this session. The most recent successful full
execution is documented in `docs/stage15-system-acceptance.md`: 274 backend
tests and 105 frontend tests, with disposable data only.

### Browser evidence

No browser-driven test was completed in this session. The owner confirmed the
restored application and normal login, but the computer-use bridge remains
unavailable. Direct Windows HTTP clients in this restricted session fail before
the request because Schannel cannot acquire credentials, while TCP connectivity
to port 43873 succeeds. No prior browser/Excel result is relabelled as a Stage
15.4 pass.

## Financial reconciliation

No current development records were read or changed, so this stage has no new
live financial reconciliation. The prior disposable acceptance evidence remains
the applicable technical evidence: recognized sales, recorded item sales and
payment allocations reconciled exactly; visitor Finance and Salary Deduction
rules were separately verified; Pending orders were excluded from recognition.
See `docs/stage15-system-acceptance.md` for its synthetic values and boundaries.

## Defects and blockers

| Priority | Finding | Impact | Required action |
| --- | --- | --- | --- |
| P2 | Browser automation is unavailable in this UAT session. | Prevents independent desktop/tablet/mobile interaction evidence and current-period Excel download checks. | An authorized tester should complete the concise browser checklist below with an existing account. |

No P0/P1 data-integrity or confirmed application-business defect was found in
this read-only pass.

## Required browser-UAT completion checklist

1. Confirm `https://192.168.45.145:43873/` and `/health` return 200 under
   normal certificate validation on an authorized workstation.
2. Sign in using an existing authorized development account; do not create test
   accounts or mutate existing business data.
3. At 1440px, 768px and 390px, read-only check navigation, Orders list/detail,
   Menu, Customers, Reports, Users and Activity Logs according to role.
4. In Reports, inspect Daily, Weekly, Monthly and Custom period changes and
   download a workbook only if an existing authorized period is available.
   Confirm its four-sheet structure without changing financial records.
5. Use a disposable PostgreSQL/app environment—not this development database—
   for employee/visitor create, edit, receipt and reversal workflows.
6. Record the resulting browser evidence and then reassess pilot readiness.

## Operational limitations before production use

- Complete the remaining live browser acceptance above with authorized roles.
- Keep write-path UAT isolated from the preserved development data.
- Resolve the previously documented operational hardening/cutover gates before
  any production decision; this stage neither changes nor supersedes them.

## Files and environment protection

Only this report was created. No application source, infrastructure,
credentials, databases, volumes, services or business records were modified.
No Docker restart, migration, reset, seed, commit or push was performed.

## Continuation record

The Stage 15.4 continuation was performed after the owner restored the gateway
port mapping and confirmed load/login. It added no business writes. The test
session verified TCP reachability to port 43873, reran no application code, and
could not conduct browser automation because the local computer-use bridge was
unavailable. This report therefore keeps all interface-specific scenarios as
**NOT TESTED** rather than overstating owner confirmation or prior-stage tests.
