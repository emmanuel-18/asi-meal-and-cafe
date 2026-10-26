# Premium Excel reporting implementation plan

Status: prerequisite review and implementation plan; workbook implementation and acceptance are not complete.

This plan translates the owner's approved **Premium Excel Reporting — Final Design Specification** into a bounded sequence. Preserve the current exports until the replacement passes the gates below. Deliver exactly four worksheets: **Executive Dashboard**, **Daily Sales**, **Salary Deduction List**, **Mode of Payment**. Do not begin branding or other stages.

## Scope and environment

- Keep current Received-only recognition, inclusive Asia/Manila service dates, Monday–Sunday weeks, historical snapshots, report authorization and all five payment methods.
- Export the full authorized period irrespective of the employee search. Do not query today's employee directory to fill historical values.
- Replace the format dropdown with one **Download Excel** action when the replacement workbook is ready. Remove PDF from the Reports UI without redesigning the dashboard or prematurely deleting shared export helpers/dependencies.
- The attachment names HTTPS port 43871. The owner's subsequent/current development configuration is `asi-meal-dev`, `DEV_WEB_PORT=43873`. Use the configured development port; do not change ports to implement exports. Confirm project/container ownership before any future frontend rebuild; a port number alone does not establish environment identity.
- Planning requires no database connection, container operation, dependency installation or service restart. Future integration tests use a separate disposable PostgreSQL database and synthetic records; artifact tests use in-memory fixtures.

## Verified implementation baseline

| Source | Current behavior and implication |
| --- | --- |
| [Export builder](../apps/web/src/lib/report-export.ts) | ExcelJS generates Executive Overview, Detailed Report and SD Register; no native Excel chart or formula-driven matrices exist. PDF generation shares section helpers. Preserve existing safe text and numeric-money handling while replacing the XLSX path. |
| [Frontend contract](../apps/web/src/lib/reports.ts) | `ReportBundle` contains period sales/category/item aggregates, period payment totals and SD order snapshots. It does not expose every Received order or per-date sales/payment totals. |
| [Reports workspace](../apps/web/src/components/reports-workspace.tsx) | Downloads receive the complete loaded bundle, separately from on-screen employee matching. Keep that separation and existing loading/error safeguards. |
| [Report service](../apps/api/src/asi_meal_api/reports.py) | Each bundle uses one authorized PostgreSQL `REPEATABLE READ`, `READ ONLY` transaction. Sales and allocations aggregate separately to avoid item/payment join multiplication. Reuse this boundary. |
| [HTTP reporting routes](../apps/api/src/asi_meal_api/business_http.py) | Bundle uses validated daily/weekly/monthly/custom parameters and authenticated actor dependency. Reuse these rules; do not create an export-specific permission or bootstrap endpoint. |
| [Persistent snapshots](../apps/api/src/asi_meal_api/db/models.py) | Orders retain service date, original menu ID, customer reference/name and organizational snapshots. Order items retain offering ID, name, category, unit price, quantity and generated line total. Allocations retain exact per-category amounts. Existing records support the proposed read extension without a schema change. |
| [Dependencies](../apps/web/package.json) and lockfile | Locked ExcelJS 4.4.0, transitive JSZip 3.10.2; current chart support must be demonstrated outside ExcelJS's undocumented internals. Do not assume a transitive package is a stable public application dependency. |
| [Frontend tests](../apps/web/tests/reports.test.mjs) and [PostgreSQL tests](../apps/api/tests/test_reports.py) | Existing coverage includes export reopening, text identifiers, formula-like text, cents, Received reversals and consistent concurrent snapshots. Some export fixtures intentionally exercise isolated features rather than fully reconciled datasets; build new reconciled fixtures for acceptance. |

## Data coverage and smallest proposed extension

| Requirement | Available now | Missing before implementation |
| --- | --- | --- |
| Sales, Received count, meals/items, allocations and SD KPIs | Period aggregates | Average order value and difference can derive from exact supplied amounts; no new business calculation policy needed except displayed average rounding. |
| Category chart for a single day | Category quantities/amounts | Nothing. |
| Top dishes | Recorded item aggregates with offering/name/category/price distinctions | Define ranking/grouping explicitly; never merge unrelated identities solely by name. |
| Payment mix | All five period payment totals | Nothing. |
| SD campaign chart and list | Per-order SD amounts, employee numbers and name/position/campaign/LOB snapshots | Nothing for historical SD rows; require exact reconciliation and omit zero-period employees. |
| Daily sales trend and payment matrix | Period-only totals | Daily sales/count/quantity and daily five-method allocations. |
| Customer sales matrix and long-period ledger | Aggregated items; customer details only for SD orders | All Received orders with their recorded customers, items and allocation categories. |
| Date-specific dish columns | Not in bundle | Assigned menu offerings per date plus original order-menu provenance and recorded items, read together with report records. |

Propose an opt-in `include_export_details=true` on the existing bundle read. Its default remains the present lightweight contract. Implement an optional export-detail payload using the same transaction as the existing summaries, not separate paged Orders/menu requests. Finalize the exact response types in the first implementation step; this plan does not change the API.

For the new XLSX workflow, load the enriched bundle once for the selected period, and keep the workspace summaries and download tied to that same object. Changing period clears eligibility until the new bundle finishes; refresh replaces it atomically. Do not fetch detail later and combine it with older loaded totals. Preserve cancellation/stale-response handling and server authorization. No employee search parameter participates in the export request.

Minimum added data:

- `export_details.orders`: one record per currently Received order, with `order_id`, `service_date`, recorded `menu_id`, customer type, employee number or visitor ID/reference, name/position/campaign/LOB snapshots, exact order total, and separate `items` and `allocations` arrays.
- Each item: line identity, source menu offering identity, recorded item name/category/unit price, quantity and line total. Each allocation: category and decimal-string amount. No actor, request key, credentials or unrelated customer fields.
- `export_details.menu_dates`: selected-range date, current assigned menu ID (nullable when unassigned), and its saved menu-offering identities/names/categories/prices. Original order menu IDs remain separate. These assignment records describe the assignment at report time, not an inferred historical assignment at sale time.
- `export_details.daily`: ordered dates with exact recognized sales/counts and five-method allocation totals, computed from the same Received set. Include selected dates with zero activity for honest time-series continuity; label them as zero recorded sales.
- All money remains decimal strings across HTTP. Verify order, item, allocation, daily and period totals in integer centavos before generating a file. Reject an incomplete/truncated or inconsistent payload with actionable error feedback.

Do not join raw item and allocation rows into one sum. Query details independently/batch-load them under the same snapshot and group by order identity. Read menu offerings from saved menus without changing them. Never reconstruct a sale from a catalog, menu assignment, or HRMS import. Current assigned offerings provide possible blank matrix columns only; all actual quantities and money use order snapshots.

For large responses, set and test explicit resource limits before release. A limit must fail visibly and must never silently truncate a report or label a partial file as full-period. Streaming/pagination architecture is outside this initial plan.

## Gate 1: one native-chart proof before the full workbook

Make one bounded prototype using synthetic in-memory values and the existing ExcelJS writer. Retain the generated XLSX and evidence outside application source. Do not invest in dashboard styling until it passes.

Proposed method: post-process ExcelJS's public `writeBuffer()` output with JSZip's public ZIP interface. Before adopting this method, review the installed ZIP package's compatibility/security and declare a direct compatible dependency if application code imports it. Do not access ExcelJS private worksheet/model objects or install a large workbook replacement.

1. Generate Executive Dashboard with five payment labels and numeric amount cells; write the workbook normally.
2. Add one OOXML chart part, drawing part and their relationship files. Resolve sheet parts through workbook relationships rather than assuming physical `sheet1.xml` identity. Allocate collision-free drawing/chart IDs and relationship IDs.
3. Add the worksheet drawing relationship and element, drawing-to-chart relationship and required `[Content_Types].xml` entries. Use correct OOXML namespaces, schema element ordering and cell anchors. Preserve every unrelated ZIP entry and existing relationship.
4. Create a native horizontal bar chart referencing the actual five worksheet labels and numeric money cells, with matching cached category/value data, zero categories retained, explicit title and no external relationships. Escape XML text; only trusted generated references become chart formulas.
5. Verify ZIP/XML structure, references, amounts and all worksheet formatting/text identifiers after reopening through ExcelJS. An ExcelJS reopen alone does not prove chart preservation or rendering; reserializing via a reader without chart support could discard chart parts.
6. Open the resulting file in Microsoft Excel: no repair dialog, chart visible, chart editable, series references correct. Change one source value and verify the chart updates, then revert it. Validate recalculation and save/reopen. Use an independent compatible spreadsheet reader where available, recording which program/version was actually used.

Exit gate: real chart editing and compatibility evidence, not a PNG or ZIP-only assertion. If no compatible rendering application is available, mark the proof pending owner acceptance and stop full dashboard implementation. If this one method fails validation, report the concrete failure and retain the existing exporter; do not start another chart-library investigation automatically.

## Gate 2: four-sheet implementation

### Executive Dashboard

Use navy heading/logo, reporting-period subtitle, eight KPI areas, restrained blue/orange accents and off-white surfaces. Use an existing approved logo asset; browser XLSX drawing support may require a bundled raster derivative of that SVG, never a screenshot crop or remote fetch. Hide presentation gridlines, keep chart bounds inside the print area, and use readable cell geometry.

Show recognized sales, Received orders, meals, items, average order value, SD, total allocations and sales-minus-allocations difference. Zero orders produces an unavailable average, not a division error. A reconciled indicator requires exact zero centavos; empty periods explicitly say no Received orders. Reconciliation describes allocation arithmetic only, not payment verification.

Charts reference numeric source tables on these four sheets (no fifth hidden worksheet): actual daily sales for multi-day periods, sales by category for one day, five-method payment mix, top recorded dishes by quantity, and SD by recorded campaign only when exact reconciliation succeeds. Suppress the SD chart and explain unavailable reconciliation when needed; missing campaign snapshots use a clearly labeled unrecorded group, not the current HRMS campaign.

Proposed top-dish key: source offering ID plus recorded name/category; sum quantities across recorded price variants only for the quantity ranking. Keep every price distinction in sales detail. Use stable tie-breaking; do not rank employees. Generate up to three factual insights from nonempty validated data, such as highest-quantity item, predominant allocated method, and SD share. Handle tied leaders honestly. An SD share is an allocation share, not payroll completion.

### Daily Sales

For daily/short ranges, group columns by date. Start with customer reference/name/type and recorded campaign/position. Group customer rows by reference **and recorded attributes**, so namesakes and changed snapshots cannot overwrite each other.

For each date, use the union of that date's assigned saved-menu offerings and all eligible recorded item variants from Received orders on that date. A historical item outside the current assignment remains included. Do not copy one day's menu into another. Disambiguate equal names by source offering/category and recorded price; distinct historical unit prices get separate columns. Extra Rice appears when assigned or recorded. Quantity cells are blank for no purchase; an actual free item has its real quantity and a numeric zero amount.

Each date group ends with a formula-derived date sales total and payment indicator. Derive the indicator from nonzero actual categories across the row/date: one method name or Split. It must not imply each item was individually paid by a particular method. Keep exact allocations in Mode of Payment. Cache date/row/grand formula results from the same centavo arithmetic and cross-check against authoritative totals.

For monthly/long custom ranges, use the specified item ledger: date, order reference, customer reference/name/type, campaign/position snapshots, recorded dish/category, unit price, quantity and line total. Include a separate daily summary and period total without duplicating line values inside the autofilter's data range. Preserve original line IDs for deterministic ordering. Use formula line totals, cached exact results, repeated print headers, frozen identifier/header panes and filters.

Proposed presentation thresholds (not financial policies): matrix only for daily/weekly/custom periods of at most seven inclusive days **and** at most 60 total worksheet columns; otherwise ledger. Monthly always uses the ledger. Document the chosen layout in the workbook; never drop eligible lines to meet a column budget.

### Salary Deduction List

Include employees whose exact period SD total is greater than zero; exclude visitors and employees with no deductions. Group rows by employee number plus recorded name/campaign/position/LOB tuple. Different attribute tuples remain separate; top employee count is the distinct employee-number count, not the number of snapshot rows.

Matrix dates contain sums of actual SD allocations, never total order amounts or flags. Use formulas and cached results for row/date/period totals. Summary includes dates, distinct employees, total SD and reconciliation against the bundle's SD total and payment-category SD total. Preserve the disclaimer that allocated SD does not establish payroll processing.

Proposed layout: at most 31 inclusive dates uses the matrix; longer custom periods use the transaction register with date/order/employee/snapshot/SD columns and explicit daily/period summaries. Empty periods contain headings and an empty-state message, no fabricated employee rows.

### Mode of Payment

One row per inclusive date: Cash, GCash, Salary Deduction, Incentive, Finance, total allocated, recognized sales, difference. Zero-day money cells are numeric zero. Split orders contribute only each allocation's actual amount. Formula totals/differences have cached exact results, with a bottom period row and top reconciliation statement. Apply restrained conditional formatting to nonzero differences. No For Deposit category.

## Financial and spreadsheet safeguards

- Python `Decimal` and browser `bigint` centavos remain the source for validation; never total currency using binary floating-point arithmetic.
- Preserve the existing tested Excel numeric-conversion boundary in `excelMoney`, but apply it to every amount, formula operand and cached result. Numeric values get peso currency number formats; employee identifiers always remain strings with text formatting, including leading zeros.
- Excel arithmetic is not arbitrary-precision decimal arithmetic. Use explicit two-decimal rounding in monetary formulas and compare cached results to authoritative centavos. Do not claim exact recalculation for values outside tested safe numeric limits. For such values, retain exact decimal text and mark dependent calculations/charts unavailable, rather than summing text as zero or plotting rounded data. Agree a clear user-facing limitation before release.
- Average order value is a derived display measure: recommend rounding the exact sales/count ratio to two decimals using half-up rounding, with no change to sales or allocations. Test ties and zero count. Document the display rounding.
- Write untrusted names/campaigns/identifiers as literal string cells, never formula objects or hyperlinks. Only trusted generated code writes formulas. Sanitize filenames using validated server dates and a fixed prefix; do not include customer names.
- Include cached formula results, `fullCalcOnLoad`, and direct tests of references/caches. Test real Excel recalculation independently; cached values alone do not demonstrate it.
- Consistent Cardo/Open Sans styling can use local Excel-installed fonts with documented substitution on other machines. Wrap and size long text rather than shrinking it until unreadable. Use color-coded date headers, frozen identifiers, appropriate autofilters, repeated print headers and landscape print areas.
- No external workbook links, macros, browser credential storage, unnecessary personal fields or exported secrets. Do not log full customer data or use real employee exports in fixtures.

## Implementation sequence and acceptance evidence

| Step | Smallest change | Required proof before proceeding |
| --- | --- | --- |
| 1 | Finalize opt-in export payload and layout thresholds; implement narrowly scoped read-only reporting additions with existing authorization. | Disposable PostgreSQL tests for snapshot consistency, dates, historical data and exact independent sums; no schema/migration change. |
| 2 | One OOXML native payment chart prototype using synthetic cells. | Microsoft Excel open/edit/recalculate/save proof plus package/reopen tests. Stop if the native-chart gate cannot pass. |
| 3 | Separate pure XLSX builder from browser download delivery; build three supporting sheets, then Executive Dashboard using their validated numeric sources. | Four sheets in exact order; complete selected period; formulas/caches; no current-HRMS reconstruction; all monetary reconciliations. |
| 4 | Replace toolbar format menu with one Download Excel button using existing loading/error behavior and complete enriched bundle. | Employee search does not affect scope; keyboard/touch behavior; correct filename; no PDF UI option; no dashboard redesign. |
| 5 | Artifact, browser and Docker acceptance in identified `asi-meal-dev`. | Checks below, real Excel rendering, authenticated synthetic download; rebuild/reload only identified development frontend/API where changed. Never operate on another stack by port alone. |

Focused synthetic cases must include:

- The reconciled P245 order: Vegetable P50, two Non-vegetable meals P150, three rice P45; GCash P200 + Cash P45. Also test all five methods, employee SD and visitor Finance-only records.
- Daily, Monday–Sunday weekly, month/leap-year boundaries and inclusive custom ranges; threshold boundaries and empty/unassigned dates.
- Pending exclusion, Received reversal and re-marking without duplication; concurrent transition during export returns one consistent snapshot.
- Menu reassignment, retired dishes, changed catalog prices, two recorded prices for one dish/date, and changed HRMS attributes after sale; all original snapshots survive.
- Same-name customers, leading-zero identifiers, long Unicode names/campaigns, missing campaign, and multiple snapshot tuples for one employee; distinct employee count and campaign sums still reconcile.
- SD-zero employees and visitors excluded from SD List, SD split orders count only SD amounts, nonzero reconciliation differences never labeled reconciled.
- No-purchase blank versus actual zero-price purchase; decimal cents, large-number fallback and formula cached values; injection-like text remains string typed.
- Full-period export with a restrictive on-screen employee search; cancelled/stale report loads, HTTP 401/403/failure, and no partial download.
- Native chart relationships/content types/anchors/series/caches, source-value changes in Excel, all sheets opening with no repair dialog, filters/frozen panes/print preview, and no clipped long names.

Run full frontend tests, ESLint, TypeScript, production build and `git diff --check` after implementation. Run relevant reporting/authenticated HTTP regressions through the established disposable PostgreSQL harness for the read extension. Keep real Excel and browser acceptance separate from automated test claims. Rebuilding a Docker image does not establish workbook rendering compatibility.

## Decisions and gates still open

1. Approve implementing the opt-in read-only reporting extension; the current bundle cannot support accurate Daily Sales and daily payments as specified. This blocks those sheets and the trend chart, not schema planning.
2. Native chart proof and Microsoft Excel availability are acceptance gates. No native chart is implemented or verified by this plan. Do not claim the original chart requirement is satisfied.
3. Confirm proposed matrix limits (seven days/60 columns; SD 31 dates), quantity-ranking grouping, and average-display rounding. These can be configured as presentation choices but should be settled before acceptance fixtures/layouts are finalized.
4. Establish a tested response/workbook size limit and owner-visible handling of amounts exceeding safe Excel numeric precision. Never silently truncate or downgrade exact totals.

This planning pass creates no workbook, changes no application behavior, removes no PDF option, adds no dependency and performs no database/service operations. Existing exports remain available pending the gated replacement.
