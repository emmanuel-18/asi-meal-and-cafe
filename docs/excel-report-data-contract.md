# Excel reporting data contract (Stage 14E.2)

Backend only. This extension does not generate workbooks or change the dashboard,
chart prototype, PDF exports, authentication or financial rules.

## Request and compatibility

Use the existing authenticated `GET /api/reports/bundle` with
`include_export_details=true`. All existing period parameters retain their rules:

```text
/api/reports/bundle?mode=daily&day=2040-01-02&include_export_details=true
/api/reports/bundle?mode=weekly&day=2040-01-02&include_export_details=true
/api/reports/bundle?mode=monthly&year=2040&month=1&include_export_details=true
/api/reports/bundle?mode=custom&start=2040-01-01&end=2040-01-03&include_export_details=true
```

Without the flag (or with false), the response remains the original three keys:
`sales`, `payments`, `salary_deduction`. With true, the response adds only
`export_details`. Monetary values serialize as decimal strings, never floats.
Employee numbers remain strings, including leading zeros. Dates are inclusive
Philippine operational **service dates**, not recording/receipt timestamps.
Weekly periods are Monday–Sunday; monthly periods use the calendar month.

Admin, Assistant Admin and Super Admin retain existing report access. Normal
session authorization applies; disabled users, unauthenticated clients and users
requiring password change cannot read this report. Response caching remains
`no-store`. No export-specific administrative endpoint or permission is added.

Employee search is not a report parameter. `q`, employee-number filters, order-list
offsets and limits cannot restrict this dataset. There is no export pagination or
silent row limit. As a resource safeguard for dense per-date output, the opt-in
supports at most **3,660 inclusive dates**; longer requests return explicit HTTP
422 asking for a shorter period. The default bundle's period support is unchanged.
Data is returned completely for accepted periods; response/workbook memory at
unusually large order volumes still needs performance acceptance before rollout.

## Added payload

| Field | Content |
| --- | --- |
| `export_details.period` | Same resolved start/end as all three existing summaries. |
| `orders[]` | Currently Received orders only, sorted by service date/order ID. Fields: `order_id`, `service_date`, recorded `menu_id`, `customer_type` (employee/visitor), nullable `employee_number` and `visitor_id`, recorded `customer_name`, `position`, `campaign`, `line_of_business`, `items`, `allocations`, and exact `total`. |
| `orders[].items[]` | Ordered by recorded line number: `order_item_id`, `line_number`, `source_menu_item_id`, recorded `item_name`, `category`, `unit_price`, `quantity`, `line_total`. Distinct historical prices/names/categories remain distinct lines. |
| `orders[].allocations[]` | Only actual positive allocations, in the five-method canonical order. Each has `category` and `amount`; never repeat an order total for each payment method. Visitors must have Finance only. |
| `menu_dates[]` | Every inclusive date, sorted: `service_date`, nullable `assigned_menu_id`, and distinct sorted `recorded_menu_ids` from that date's Received orders. Unassigned/no-sale dates have null/empty values as appropriate. |
| `menus[]` | Distinct menus referenced by current in-range assignments or Received orders. Each has `menu_id` and `offerings[]`: `menu_item_id`, stable `dish_id`, saved offering `item_name`, `category`, `unit_price`. Menu/dish identity ordering is deterministic; shared menus appear once. |
| `daily[]` | Every inclusive date, including zero-sale dates: `service_date`, `recognized_sales`, `received_order_count`, `meal_quantity`, `item_quantity`, `payments`, `allocated_total`, `allocation_difference`. `payments` always contains Cash, GCash, SD, Incentive and Finance, with numeric decimal-string zero where absent. |
| `sd_campaigns[]` | Exact recorded campaign grouping: nullable `campaign` and positive `sd_amount`. Null and empty campaign snapshots remain distinguishable; the consumer may label unrecorded values without substituting current HRMS data. |

Use the existing `salary_deduction.orders` and `salary_deduction.employees` in the
same response for the SD List. Only employees with positive SD appear; no visitor
or zero-deduction employee rows are manufactured. Order-level snapshots preserve
different names/campaigns/positions/LOB for the same employee. A future matrix
must group by identity and the recorded attribute tuple, not current directory
values. Count distinct employee numbers separately from snapshot rows.

## Menu provenance and historical limits

`menu_dates.assigned_menu_id` describes the assignment **at report time**.
`recorded_menu_ids` and each order's `menu_id` preserve menus actually recorded
on eligible orders before any reassignment. The schema does not retain a complete
temporal menu-assignment schedule. Do not present today's assignment as the
assignment at sale time, or infer a schedule for a date without recorded orders.

Saved offerings support date-specific matrix columns and identity references.
All actual purchase quantities, names, categories and money come exclusively
from order-item snapshots. A historical recorded item outside today's assignment
must still be included. Saved menu/catalog or HRMS changes never rewrite export
order snapshots. No new database schema or migration is required.

## Worksheet consumers

| Worksheet | Source in this single response |
| --- | --- |
| Executive Dashboard | Existing sales/payment/SD summaries, `daily` trend or existing single-day categories, recorded item rankings and reconciled `sd_campaigns`. |
| Daily Sales | Full `orders` with recorded customers/items/allocations, `menu_dates` and saved `menus` for date columns; same data supports the long-period ledger. |
| Salary Deduction List | Existing nonzero SD employees/orders with historical snapshots and resolved dates; grouped by recorded attributes where they differ. |
| Mode of Payment | `daily` with all five allocation amounts, recognized sales, allocated totals and differences; existing summaries supply period checks. |

Stage 14E.3 must load the enriched bundle as one object for the selected period.
Keep summaries and workbook data tied to that same response; do not combine a
new detailed fetch with older totals. Changing period/refresh must invalidate old
download data until the replacement bundle succeeds. On-screen employee search
must remain independent. Do not remove PDF or change the download UI in this stage.

## Reconciliation and read-only guarantees

One fresh PostgreSQL `REPEATABLE READ`, `READ ONLY` transaction covers actor
checks, authoritative aggregates, detail rows and menu provenance. Five added
batched SELECTs retrieve all orders, items, allocations, menu dates and saved
offerings; query count does not grow per order. No current employee/visitor
directory join, audit write, account change or ORM lazy-load sequence is needed.
No hashes, sessions, request keys, contact details or actor metadata are exported.

Detail validation uses integer centavos converted from exact Decimals, without
binary floats or decimal-context rounding. Before returning success it checks:

- Each line equals recorded price times quantity; each order has items and valid
  positive allocations exactly equal to its line total.
- Visitor allocations are Finance only. All other allocations use the existing
  five categories. Employee and visitor identities remain mutually exclusive.
- Detailed order counts, line sales, item/category groups and meal/item quantities
  match the independent existing SQL aggregates.
- Detailed allocations match every category and period payment total; sales,
  allocated totals and the authoritative difference reconcile exactly.
- Derived SD order snapshots and employee totals match the independent SD query;
  recorded campaign sums match SD and the payment-category SD total.
- Each day's recognized sales equals its allocated amounts. Complete ordered
  dates partition the validated order data without pagination or duplicate joins.

Failure returns **HTTP 409** with code `REPORT_RECONCILIATION_FAILED`, a fixed
privacy-safe explanation, and no partial report. It does not adjust records,
rewrite totals, log customer values or weaken validation to force a balance.
Default report behavior is preserved. SD allocation still does not establish
that payroll processed a deduction.

## Verification and next stage

Tests live in [test_report_export.py](../apps/api/tests/test_report_export.py)
and the existing [report suite](../apps/api/tests/test_reports.py). They use only
synthetic records in the established verified disposable PostgreSQL 17 harness:

```powershell
.\.venv\Scripts\python.exe -m pytest apps/api/tests -c apps/api/pyproject.toml -p no:cacheprovider --postgres -q
```

Stage 14E.3 can consume this opt-in contract without another reporting endpoint.
Remaining work is frontend typing/loading, the four worksheet builders, formula
and chart integration, precision/large-volume handling, and real Excel/browser
acceptance. Preserve the separately proven native-chart approach; do not redo it.
No running development or protected deployment is modified by this backend stage.
