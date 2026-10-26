# Four-sheet premium Excel export (Stage 14E.3)

Implemented in the frontend. The ordinary dashboard bundle and the existing
PDF action remain unchanged. The workbook generation code uses the Stage 14E.2
[read-only data contract](excel-report-data-contract.md); it does not query
employees, menus or orders separately and never changes records.

## Export request and safeguards

Only choosing Excel fetches `GET /api/reports/bundle` with the selected period
parameters and `include_export_details=true`. The new response's summaries and
details are used together; old displayed totals are never mixed with new details.
Employee search is not included. Changes to period/refresh abort an outstanding
export, and a late response cannot initiate a download. Duplicate clicks are
guarded while the operation is active. HTTP 409 has explicit reconciliation
feedback; the 3,660-service-date backend limit is checked before requesting data.

Before building the workbook, independent integer-centavo checks compare orders,
item/category totals, allocation totals, daily rows, SD snapshots/employee totals
and campaign groups. Missing dates, duplicate identities, visitor non-Finance
payments and mismatched totals are rejected. The download is created only after
all validation and ZIP processing succeed.

## Worksheets

1. **Executive Dashboard** — eight KPI areas, exact period, reconciled indicator,
   factual insights, and native chart drawing areas above organized source tables.
   Multi-day periods show actual daily recognized sales with straight lines;
   single days use a category comparison. All five payment methods remain in the
   payment chart. Top ten recorded item variants retain their source/price
   distinctions. Reconciled SD campaigns have a separate chart; empty periods
   omit unsupported rankings/SD charts and display a defined empty state.
2. **Daily Sales** — at most seven dates uses a customer/snapshot matrix with
   grouped dates, relevant assigned offerings and historical recorded variants.
   Numeric recorded-price rows feed `SUMPRODUCT`; no-purchase cells remain blank.
   Actual purchases at zero price remain distinguishable by quantity. Multiple
   methods yield Split. More than seven dates uses an item ledger with line
   formulas, period total and formula-driven daily summaries.
3. **Salary Deduction List** — only positive employee SD allocations. At most
   31 dates uses a date matrix; longer periods use a transaction register. Changed
   recorded attributes create distinct rows, while the summary counts distinct
   employees. Includes the payroll-completion disclaimer and exact SD total.
4. **Mode of Payment** — one row per inclusive date, all five methods, formula
   allocation totals, recognized sales and differences, plus a period summary.
   Conditional formatting exposes nonzero differences if workbook values are edited.

ASI navy, blue, orange and off-white distinguish headings, supporting areas and
totals. Detail sheets have filters, frozen identifiers/headers, wrapping, cached
formula results, print areas and repeated headers. Wide tables use supported
landscape Legal settings; particularly wide matrices retain readable scale and
repeat identifier columns across horizontal print pages. Dashboard printing
excludes its supporting source tables while leaving them visible on the sheet.

## Financial and text handling

- All validations and aggregate calculations use integer centavos. Monetary
  formulas have two-decimal rounding and exact cached results. Average order
  value uses half-up centavo rounding and is undefined for zero orders.
- Numeric conversion retains the existing conservative 15-digit centavo
  boundary and verifies round-trip cents. Unsafe values fail the entire export
  with a precision explanation; they are not silently rounded or summed as text.
- Employee identifiers remain literal text, including leading zeros. Imported
  strings never become formula objects or external links. Only generated trusted
  formulas and fixed worksheet references enter OOXML formulas.
- The workbook refuses excessive text/column limits rather than silently dropping
  records. Long chart labels may use numbered source-table references; the full
  names remain wrapped in the source table or detailed sheets.
- Saved menu offerings provide date-specific columns only. Recorded order/item
  snapshots supply all actual purchases and prices, including historical items
  outside the current assignment. No current HRMS reconstruction occurs.

## Native chart implementation and runtime

`src/lib/excel-charts.ts` promotes the Stage 14E.1 mechanism: standard chart XML,
drawing XML, internal relationships, content types and caches are inserted after
ExcelJS writes the workbook. Multiple charts share a dashboard drawing with
nonoverlapping cell anchors. The target sheet is resolved through workbook
relationships; existing parts are retained and new part/relationship IDs are
allocated without collisions. An existing target drawing is refused rather than
overwritten. XML text is escaped and generated series references are restricted
to the four known sheets. No chart images or undocumented ExcelJS chart methods
are used.

JSZip 3.10.2 is now an explicit production dependency at its existing version.
The merger emits browser-compatible `Uint8Array` output, with no Node filesystem
dependency in application code. A separate verification image built with the
existing production Dockerfile generated a workbook in memory on Node 24 with
no network, no published ports, a read-only filesystem and a synthetic fixture.
It did not start or replace a running deployment.

## Reproduce synthetic artifacts

From `apps/web`, choose a fresh artifact directory (existing files are not overwritten):

```powershell
node scripts/generate-premium-excel.mjs ../../exports/premium-excel-final-20261026
```

From the project root:

```powershell
.\.venv\Scripts\python.exe apps/web/scripts/verify-premium-package.py exports/premium-excel-final-20261026/manifest.json
powershell.exe -NoProfile -ExecutionPolicy Bypass -File apps/web/scripts/verify-premium-excel.ps1 -ManifestPath exports/premium-excel-final-20261026/manifest.json -EvidenceDirectory exports/premium-excel-final-20261026/excel-evidence
```

The child-process execution policy does not change Windows policy. The Excel
verifier opens a new instance, disables macros, uses normal read-only file opens,
keeps alerts enabled, recalculates, renders charts and tests edits in separate
copies. It verifies original file hashes and closes only its own instance.

Artifacts use synthetic fixtures only: daily, weekly, monthly, 32-day custom,
long text and empty periods. Manifest totals are respectively 195.03, 660.01,
2520.00, 2660.01, 800.00 and 0.00. Independent ZIP/XML validation checks every
relationship target, chart source/cache, content type, cached formula and chart
anchor, and confirms four worksheets with no external relationships/macros.

Microsoft Excel 16.0 build 14334 opened all six final workbooks. Recalculation
matched the fixture totals on dashboard, Daily Sales, SD and payments. Source
edits updated native charts; chart-title edits survived save/reopen. Original
workbooks stayed unchanged. Rendered payment/category/trend/top-item/campaign
charts were inspected for readable labels, proportions and zero values.

## Remaining acceptance and Stage 14E.4

Excel's PDF-print conversion stalled for the report and also for an independent
one-cell synthetic workbook. The identified test automation instances were
cleaned up; the owner's pre-existing Excel sessions were preserved. Print
settings and formula results were inspected through Excel, but rendered print
pages and full worksheet visual acceptance remain outstanding. The verifier's
optional `-PrintPreviews` flag should only be used after local print conversion
is working; it is not part of the default successful verification.

At completion of Stage 14E.3, authenticated browser download, remote-device
acceptance and full-volume stress testing remained outstanding. That stage did
not access running endpoints, restart services, modify databases or change the
backend. Its protected-port restriction prevented deployment at that time.
For Stage 14E.4 the owner explicitly confirmed port 43873 as development;
the runtime identifies `asi-meal-dev` from `infra/dev/compose.yaml` with persistent
volume `asi-meal-dev_dev_postgres`. This supersedes the historical restriction.

Stage 14E.4 may remove the PDF option and simplify the toolbar after workbook
acceptance. This stage intentionally leaves that UI and PDF generation intact.
No branding stage has begun.

## Verification and changed files

Final frontend checks: 100 tests passed, none failed or skipped; ESLint,
TypeScript (`tsc --noEmit --incremental false`), production build and
`git diff --check` passed. All six synthetic packages passed the independent
ZIP/XML/cached-value verifier. Existing backend work was preserved; no backend
files were edited during this stage.

Files changed or added during Stage 14E.3:

- `apps/web/package.json`
- `apps/web/package-lock.json`
- `apps/web/src/components/reports-workspace.tsx`
- `apps/web/src/lib/reports.ts`
- `apps/web/src/lib/report-export.ts`
- `apps/web/src/lib/premium-excel.ts`
- `apps/web/src/lib/excel-charts.ts`
- `apps/web/tests/reports.test.mjs`
- `apps/web/tests/premium-excel.test.mjs`
- `apps/web/tests/fixtures/premium-report.mjs`
- `apps/web/scripts/generate-premium-excel.mjs`
- `apps/web/scripts/verify-premium-excel.ps1`
- `apps/web/scripts/verify-premium-package.py`
- `docs/premium-excel-workbook.md`

The Stage 14E.1 prototype scripts/tests and Stage 14E.2 backend/contract changes
already present in the working tree were retained.
