# Stage 14E.4 Excel-only integration and acceptance

## Authorized development target

The owner explicitly confirmed `https://192.168.45.145:43873/` as development.
This supersedes earlier port assignments and historical protected-port labels.
Read-only Docker inspection confirmed:

- Compose project: `asi-meal-dev`.
- Configuration: `C:\asi-meal-management\infra\dev\compose.yaml`.
- Gateway: `asi-meal-dev-web-1`, Caddy, publishing LAN and loopback port 43873.
- Frontend/API: `asi-meal-dev-frontend-1` and `asi-meal-dev-api-1`.
- Database: `asi-meal-dev-db-1`, PostgreSQL 17, internal network only.
- Persistent database volume: `asi-meal-dev_dev_postgres`.
- The running API's OpenAPI schema includes `include_export_details` on the
  existing reporting bundle route. No API restart was needed.

Only the frontend was rebuilt and recreated, using:

```powershell
cd C:\asi-meal-management\infra\dev
docker compose build frontend
docker compose up -d --no-deps --no-build frontend
```

The API, database and gateway retained their original container identities.
No database reset, migration, seed operation or port change was performed.

## Implementation

Reports now offers one native **Download Excel** button, with a download icon,
44px minimum height, disabled/loading states and `aria-busy`. PDF is no longer
offered in the workspace; its implementation and unrelated helpers remain.
The existing full-period request, cancellation, duplicate-click guard, employee
search independence and explicit HTTP 409 reconciliation feedback remain.

Actual Excel Print Preview revealed that the dashboard's bottom charts split
across pages. A targeted `fitToHeight=1` setting now keeps the dashboard on one
landscape page. No calculations or workbook architecture changed.

## Actual authenticated downloads

The owner signed in normally in Responsively. No credentials or browser session
tokens were extracted. Downloads were initiated through the visible Reports UI.

| Mode | Inclusive period | Recognized sales | SD | Result |
| --- | --- | ---: | ---: | --- |
| Daily, empty | 2026-10-26 | 0.00 | 0.00 | Downloaded |
| Weekly, empty | 2026-10-26 through 2026-11-01 | 0.00 | 0.00 | Downloaded |
| Monthly, populated | 2026-10-01 through 2026-10-31 | 1470.00 | 1025.00 | Downloaded |
| Custom, 32 days | 2026-09-25 through 2026-10-26 | 1470.00 | 1025.00 | Downloaded |
| Daily, populated, after print fix | 2026-10-23 | 1470.00 | 1025.00 | Downloaded |

Artifacts and manifest are under the ignored directory
`exports/stage14e4-acceptance-20261026/`. Filenames retain the generated
`asi-meal-report-<start>-to-<end>.xlsx` convention. Existing older downloads were
not overwritten by automation. Responsively mirrors clicks across device panes;
unintended additional final-download dialogs were cancelled.

All five packages passed the independent ZIP/XML/cached-value verifier: four
worksheets in the approved order, numeric chart references, valid relationships
and content types, no external links, intact cached formulas and exact totals.
ExcelJS independently reopened the first four downloads and confirmed adaptive
matrix/ledger/register structures, frozen panes, filters, numeric cached totals,
text employee references and positive-only SD rows. The final daily download's
dashboard XML explicitly has `fitToWidth=1` and `fitToHeight=1`.

The populated dashboard reports six Received orders, 22 meals, 30 items, sales
1470.00, allocations 1470.00, Cash 445.00, SD 1025.00, other methods zero and
zero reconciliation difference. Four employees have nonzero SD. Recorded
campaign allocations 745.00 and 280.00 reconcile to 1025.00. No records were
created to obtain these scenarios.

## Excel visual checks actually performed

Microsoft Excel opened the downloaded October monthly and final populated daily
workbooks. The owner enabled editing personally when Protected View prevented
Print Preview; automation did not bypass security settings.

- Monthly: inspected all four worksheets, dashboard KPIs/native charts, item
  ledger, wrapped customer/organizational fields, SD matrix and payment matrix.
- Monthly print: inspected Daily Sales pages 1 and 2, SD page 1 of 7, and Mode of
  Payment pages 1 and 2. Landscape layouts and repeated headers were visible.
- Dashboard: the original monthly preview exposed the split-chart defect.
  The final daily download's corrected preview shows **Page 1 of 1**, all four
  charts intact and readable KPIs, with no drawing crossing a page boundary.
- Final daily: inspected the populated sales matrix and its one-page Legal
  landscape preview, including prices, quantities, payment indicators and totals.
- The unavailable physical printer initially prevented preview. Selecting the
  already-installed Microsoft Print to PDF in Excel enabled preview. No print
  job was submitted or Windows printer/security settings changed.
- The Download Excel action was visibly usable in Responsively's 1440x900,
  768x1024 and 390x844 views, with no clipped/wrapped button label.

Remaining acceptance limitations:

- The monthly ledger's continued daily-summary page repeats ledger headings.
  The 31-day SD matrix spans seven horizontal pages; only its first page was
  visually inspected. Mode of Payment carries its last date/total onto page 2.
  These print-density/continuation issues remain for owner review.
- The downloaded 32-day SD register passed package/data checks but was not
  visually inspected in Excel during this stage.
- Extreme long names, leading-zero numeric identifiers, split allocations and
  historical snapshot changes remain covered by existing synthetic tests where
  not represented in the available live reporting period.
- Employee-search independence, cancellation and HTTP 409 handling passed
  automated interaction tests; they were not separately forced in the live UI.
- Save/reopen and chart-source editing were verified in Stage 14E.3 synthetic
  Excel acceptance; they were not repeated on the live downloaded workbooks.

## Checks and files

Final checks: **101 frontend tests passed**, none failed or skipped; ESLint,
TypeScript, production build and `git diff --check` passed. HTTPS verification
with the existing public development CA passed: frontend/health 200,
unauthenticated session/protected route 401, docs/schema gateway routes 404 and
untrusted login Origin 403. Runtime review found successful enriched-report GETs
with no server-error responses or module/proxy/traceback errors in the inspected
window. The final frontend, API and database are healthy.

Files changed during this stage (earlier work preserved):

- `apps/web/src/components/reports-workspace.tsx`
- `apps/web/src/app/globals.css`
- `apps/web/src/lib/premium-excel.ts`
- `apps/web/tests/premium-excel.test.mjs`
- `infra/dev/README.md`
- `docs/premium-excel-workbook.md`
- `docs/excel-export-acceptance.md`

No backend, authentication, financial rules, dependencies, schema or business
records were changed. Normal owner sign-in retained existing session/audit
behavior. No unrelated Docker stack was rebuilt, and no commits or
pushes were made. Stage 14G.4 has not begun.

## Stage 14E.4A — focused print refinement

Implementation and automated verification completed; final Excel visual acceptance
is **incomplete** because Windows automation could not activate the listed Excel
window. Initial activation and the documented refresh/recovery attempt both
returned `failed to activate captured window`. The owner was asked to restore
Excel. No print-preview, page-count or save/reopen success is inferred from tests.

Changes:

- The long-period Daily Sales ledger remains in A:M. Its date summary now uses
  O:P on the same worksheet, with its own title, period, headers and period total.
  Two disjoint print ranges isolate the sections; repeated row 5 resolves to
  the correct columns for each section. Only column headings repeat, not titles.
  Ledger lines, totals and SUMIF calculations are preserved with the summary's
  date references updated to column O. The ledger AutoFilter stays in A:M.
- ExcelJS emits duplicate scoped Print_Area names for disjoint print ranges.
  The existing public ZIP postprocessor now combines them into a single
  comma-separated union. Tests and the independent package verifier reject
  duplicate scoped names. ExcelJS's reader exposes only the first area of a
  union, so the complete definition is checked in workbook XML as well.
- The SD employee-by-date matrix retains every date and snapshot row. Metadata
  columns are narrower, date columns start at width 10.5 and expand for large
  amounts, month groups occupy row 4 and day/month labels occupy row 5.
  Legal landscape, 0.2-inch side margins, 100% print scale and 10-point cells
  preserve readability. Employee number/name columns A:B and header rows 4:5
  repeat; the running header names the exact period and continuation behavior.
  Multiple horizontal pages are permitted. **Actual new horizontal page count
  has not been measured in Excel**; the previous observed count was seven.
- The greater-than-31-day SD transaction register and the one-page dashboard
  print setting are unchanged. The 32-day register has automated structure,
  nonzero-SD, snapshot and reconciliation coverage; its requested new visual
  inspection and real-workbook save/reopen remain outstanding.

Final automated checks: **103 frontend tests passed**, zero failures/skips;
ESLint, TypeScript and production build passed. Six freshly generated in-memory
fixtures passed independent ZIP/XML, chart-reference and cached-value checks,
including duplicate-name validation. No database was used for fixtures.
Final fixtures: `exports/stage14e4a-final-fixtures-20261026/`.

Only the verified `asi-meal-dev` frontend image/container was rebuilt/reloaded
on port 43873. API, gateway and PostgreSQL were preserved. No financial rules,
business records, migrations, dependencies or unrelated work were changed.

Files changed in this stage:

- `apps/web/src/lib/premium-excel.ts`
- `apps/web/src/lib/excel-charts.ts`
- `apps/web/tests/premium-excel.test.mjs`
- `apps/web/scripts/verify-premium-package.py`
- `docs/excel-export-acceptance.md`

Outstanding owner/Excel acceptance:

1. Restore Excel, download fresh Monthly and 32-day Custom workbooks from the
   development Reports page, and save them as new files.
2. Preview both Daily Sales print ranges: only ledger headings above lines and
   date/sales headings above summary dates. Check all continuation pages.
3. Count monthly SD horizontal pages, check repeated employee identifiers and
   date/month labels on every page, and confirm readable amounts.
4. Inspect the 32-day register's complete rows, filters, frozen panes, totals
   and Print Preview; confirm only nonzero employee deductions appear.
5. Preview every worksheet, confirm the dashboard remains one page with four
   charts, recalculate, Save As a copy, close/reopen the copy and recheck charts,
   formulas and exact authoritative sales/allocation/SD totals.

These checks are pending, not accepted. Do not start Stage 14G.4 on this evidence.
