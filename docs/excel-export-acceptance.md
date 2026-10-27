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

## Stage 14E.4A ? focused print refinement

Implementation and automated checks are complete. Excel visual checks resumed
after the owner restored Excel and enabled editing for the actual downloaded
32-day workbook. Final save/reopen acceptance was completed on October 27, 2026.
No security settings were changed or Protected View bypassed by automation.

### Changes

- Daily Sales ledger remains A:M; its daily summary is now O:P with a separate
  title, period, headers and total. Two disjoint print areas keep sections
  separate. Row 5 repeats the appropriate headings for each area. Ledger
  transactions, totals and SUMIF calculations are preserved.
- The public JSZip postprocessor combines ExcelJS's duplicate scoped Print_Area
  definitions into one OOXML union. Tests and the independent package verifier
  check relationships and scoped-name uniqueness. No private ExcelJS API or
  new dependency is used.
- SD matrix metadata/date widths, month groups and day/month headings are more
  compact. Legal landscape, 0.2-inch side margins, 100% scale and 10-point body
  cells preserve readability. Columns A:B repeat employee number and name;
  rows 4:5 repeat the disclaimer and date headers. The wide on-screen title
  was visibly clipped on horizontal continuations, so the print area now
  begins at row 4 and uses the running exact-period header. The disclaimer
  fits A4:B4 at a 44-point row height. The on-screen title remains intact.
- The greater-than-31-day SD transaction register and dashboard one-page
  setting are unchanged. Financial logic and historical snapshots are unchanged.

### Actual Microsoft Excel inspection

Final synthetic review workbook:
`exports/stage14e4a-reviewed-20261026/monthly-review.xlsx`.
Microsoft Print to PDF was selected for preview only; no print jobs were sent.

- SD matrix: **4 horizontal pages**, compared with the prior observed 7.
  All four pages were examined. Employee numbers/names, date/month labels,
  amounts, daily totals, period total and continuation footer are readable.
  No clipped title fragments remain. This is intentionally not squeezed onto
  one or two unreadably small pages. The final page contains day 31 and totals;
  it is not an unexpected blank page. Page count can vary with printer metrics
  and very large amounts that expand columns.
- Daily Sales: all **5 pages** inspected (3 ledger, 2 summary). Ledger
  continuations repeat only ledger headers; summary continuation repeats only
  service date/recognized sales headers. Main titles do not repeat. Both
  sections reconcile to the synthetic fixture's 2,520.00. No overlap or missing
  rows observed. The summary retains the worksheet's shared ledger print scale
  and consequently uses a small portion of its page.
- Executive Dashboard: **1 A4 landscape page**, all four native charts and KPIs
  visible without overlap or clipping.
- Mode of Payment: **2 A4 landscape pages**, both inspected. Final date and total
  continue on page 2 with appropriate column headers; all five methods and zero
  reconciliation difference are preserved. This short continuation is existing
  pagination, not an unexpected blank page.

Actual browser-downloaded 32-day workbook from Stage 14E.4:
`exports/stage14e4-acceptance-20261026/asi-meal-report-2026-09-25-to-2026-10-26.xlsx`.

- Complete SD register examined: four employees with nonzero deductions,
  four transactions, service dates/order references and recorded identity,
  campaign, position and LOB columns. Long fields wrap without clipping.
  SD amounts 355.00 + 280.00 + 50.00 + 340.00 = **1,025.00**.
- SD Print Preview: **1 A4 landscape page**, complete header, rows and total.
  Filters and frozen-pane structures are present; interactive filtering and
  scrolling were not exercised during this pass.
- Owner enabled editing. Excel full recalculation was invoked; Save As created
  `exports/stage14e4a-reviewed-20261026/actual-32-day-excel-saved.xlsx` without
  overwriting the download. The copy was closed and reopened in Excel.
- Reopened copy: all four native charts render. Sales/allocations remain
  **1,470.00**, Cash **445.00**, SD **1,025.00**, other methods zero and
  reconciliation difference **0.00**. SD total formula remains
  `ROUND(SUM(H6:H9),2)`. A file comparison using public ExcelJS reads verified
  **1,353 populated cells**, formulas and cached results across all four sheets
  match the original, resolving Excel's shared-formula serialization normally.
- Excel's existing Document Recovery pane was present at next-day startup;
  no recovery files were changed or discarded. The saved copy opened normally
  without a workbook repair prompt.

### Automated verification and deployment

After the final title-clipping fix: **103 frontend tests passed**, no failures
or skips. ESLint, TypeScript, production build and git diff --check passed.
Six in-memory fixtures passed independent ZIP/XML, chart references, financial
cached values and scoped-name validation. Final fixtures are under
`exports/stage14e4a-reviewed-20261026/`; earlier artifact folders are not the
final layout. No database was used to generate fixtures.

Only the identified asi-meal-dev frontend was rebuilt/reloaded by this stage.
API, gateway and PostgreSQL were not restarted by this work. Latest read-only
checks on October 27: frontend and health 200, unauthenticated session/users
401, docs/schema 404, untrusted login Origin 403. The identified development
containers are healthy and the gateway serves HTTPS on port 43873.

Files changed during this stage (unrelated work preserved):

- `apps/web/src/lib/premium-excel.ts`
- `apps/web/src/lib/excel-charts.ts`
- `apps/web/tests/premium-excel.test.mjs`
- `apps/web/scripts/verify-premium-package.py`
- `docs/excel-export-acceptance.md`

### Remaining acceptance limits

Revised monthly layout was measured with synthetic in-memory fixtures; the real
32-day SD register and save/reopen were tested using the existing authenticated
Stage 14E.4 download. Fresh post-fix authenticated browser downloads were not
repeated in this pass. All four worksheet print previews were inspected on the
final synthetic monthly workbook, not every worksheet of a fresh real download.
Interactive filters/frozen-pane behavior remains unexercised, though existing
structure/tests and reopened values are preserved. Physical printer output was
not tested. No database writes, financial-rule changes, migrations, dependency
changes, commits or pushes were performed by this work. Stage 14G.4 was not begun.
