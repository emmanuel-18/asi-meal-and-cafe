# ASI Meal Management — Business requirements

Status: documentation for review, not implemented application behavior. Sources:
the owner's latest clarifications, root `AGENTS.md` and `README.md`, and the
reference review in [Business workflow discovery](business-workflow-discovery.md).

**Confirmed** means an explicit owner requirement or existing project constraint.
**Proposed** means a recommendation awaiting approval. **Unresolved** means a
business decision is still required. Proposals are not approved implementation
specifications. The initial two-role permissions below are confirmed; any
remaining permission details are identified separately.

## 1. Purpose and business objectives

- **Confirmed:** Reduce repeated paper-to-Excel work and improve order entry,
  receipt tracking, reconciliation, and reporting for staff and Finance.
- **Confirmed:** Keep the workflow fast, simple, and usable on desktop, tablet,
  and mobile.

## 2. Users and initial roles

| Status | Role | Initial permissions |
| --- | --- | --- |
| Confirmed | Super Admin | All Admin operational permissions; manage application users. Activity-log access is planned for a later stage. |
| Confirmed | Admin | Record/manage orders, menus and reusable dishes and visitors; mark or reverse Received; view reports; import employees. No user management. |
| Confirmed | Assistant Admin | Routine orders, menus, dishes and visitors; mark Received and view reports. Cannot reverse Received, import employees, or manage users. |

- **Confirmed:** All roles use individual accounts, never shared accounts.
  Keep permissions understandable without unnecessary routine-work restrictions.
- **Proposed:** Keep role permissions clearly defined or configurable within
  the confirmed initial model.
- **Unresolved:** Site/record access and further administrative security permissions.

## 3. Scope and exclusions

- **Confirmed:** Local/on-premises core processing; HRMS CSV import; employees,
  visitors, menus, orders, receipt tracking, reports, and audit history.
- **Confirmed:** Exclude direct HRMS APIs, inventory/stock management, AI in the
  core workflow, payment gateways, GCash verification, payroll integration,
  external financial processing, and real email/SMS delivery.
- **Confirmed:** This task is documentation only; no database schemas,
  migrations, application features, or integration implementation.

## 4. Employee data and HRMS import

- **Confirmed:** HRMS is the source of truth. Import validated CSV and retain all
  successfully imported employees; impose no additional eligibility restrictions.
- **Confirmed:** Identify employees by employee number, preserved as text. Names
  and phone numbers are not unique identifiers.
- **Confirmed:** Validate structure, required fields, encoding, duplicate
  identifiers, and malformed records. Preserve import history/results and report
  rejected records clearly without unnecessary personal information or silent loss.
- **Confirmed:** Do not silently overwrite employee information or presume every
  exported field is editable in ASI Meal.
- **Proposed:** Import employee number and full name plus position and approved
  organizational fields needed for reports. Exclude contact details unless a
  specific need is approved.
- **Unresolved:** Required fields, campaign/line-of-business mapping, site
  assignments, refresh frequency, changed-record conflicts, and treatment of
  employees absent from a later export. These do not authorize eligibility filters.

## 5. Menu and dish catalog management

- **Proposed:** Maintain a reusable dish catalog with separate vegetable and
  non-vegetable categories, dropdown selection, and an add-new-dish option.
- **Proposed:** Rank dropdown choices by frequency of selection for menus, not
  quantity sold, placing common menu choices near the top.
- **Proposed:** Configure a menu for one date or reuse it across multiple dates,
  supporting daily changes and unchanged menus over several days.
- **Proposed:** Manage menus and applicable prices without repetitive dish-name entry.
- **Unresolved:** Counting menu selections when reusing menus, ranking ties,
  and continued scope of legacy hotsilog/cornsilog items.

## 6. Order entry and pricing

| Status | Category | Current working unit price |
| --- | --- | ---: |
| Confirmed | Vegetable meal, including rice | ₱50 |
| Confirmed | Non-vegetable meal, including rice | ₱75 |
| Confirmed | Extra rice | ₱15 |

- **Confirmed:** Prices are configurable, not hardcoded throughout the app.
  These values supersede the earlier without/with-rice description.
- **Confirmed:** One transaction supports multiple items/quantities. Line and
  transaction totals update automatically when quantities change.
- **Proposed:** Use plus/minus buttons or steppers for quick quantity entry.
- **Confirmed:** Preserve the applicable dish name, category, unit price,
  quantity, and relevant item details with each recorded sale. Later changes to
  catalogs, menus, or prices must not silently rewrite historical sales/reports.
- **Unresolved:** Price effective dates, overrides, and correction of recorded prices.

Synthetic example: 2 vegetable meals + 1 non-vegetable meal + 3 extra rice =
**2 × ₱50 + ₱75 + 3 × ₱15 = ₱220** at the working prices.

## 7. Employee and visitor handling

- **Confirmed:** Employee orders identify imported employees by employee number.
  Visitor meals must be supported separately from HRMS employees.
- **Confirmed:** Admin and Assistant Admin can create and reuse visitor records,
  select an existing visitor on an order, and create a missing visitor without
  unnecessarily leaving order entry.
- **Confirmed:** Visitor meals are currently associated with Finance.
- **Confirmed:** Give each visitor a stable internal identifier so name changes
  do not break historical records. Avoid duplicates where reasonably possible;
  a visitor name alone is not guaranteed unique. Use fictional examples only.
- **Unresolved:** Precise visitor fields and duplicate-handling behavior may be
  refined during database design; no database design is performed here.

## 8. Payment categories

| Status | Category | Meaning / limitation |
| --- | --- | --- |
| Confirmed | Cash | Administrative order category. |
| Confirmed | GCash | Selection does not verify a transfer. |
| Confirmed | Salary Deduction (SD) | Selection does not complete payroll deduction. |
| Confirmed | Incentive | Voucher or gift card; redemption details unresolved. |
| Confirmed | Finance | Currently associated with visitor meals; broader use unresolved. |
| Unresolved | For Deposit | Workbook label only; not an approved selectable category. |

- **Confirmed:** Staff record categories as an administrative recording/reminder
  function, not independent payment proof or external processing.
- **Unresolved:** Mixed categories per order, incentive handling, category changes,
  and detailed report presentation for each category.

## 9. Receipt tracking and corrections

- **Confirmed:** Staff record the employee or visitor, items, quantities, and
  category; the system calculates the total. After meal handover and transaction
  completion, Admin or Assistant Admin marks Received. The order is then
  considered paid under ASI Meal's internal workflow, and the staff member
  marking it is accountable. Record who marked it and when.
- **Confirmed:** Do not introduce a separate Paid/Unpaid status. Received is
  staff confirmation, not GCash verification, payroll/SD verification, or Finance
  approval of external payment processing. Do not wait for Finance or payroll
  before counting SD sales.
- **Confirmed:** Only Admin and Super Admin may reverse Received. Every
  correction retains responsible user, timestamp, affected order, action, and
  previous/new values; do not erase the original action.
- **Proposed:** Require a correction reason where appropriate; mandatory cases
  have not been approved.
- **Unresolved:** Other order corrections and refunds/cancellations.

## 10. Audit logging

- **Confirmed:** Consequential corrections retain verified actor, timestamp,
  affected record, action, previous/new values, and reason where required. Never silently
  erase correction history.
- **Confirmed:** Log important actions: creating/updating orders; marking,
  reversing, or correcting Received; creating/updating menus and visitors;
  employee imports; and administrative user/role changes. Include actor, time,
  affected record, action, and before/after values where applicable.
- **Confirmed:** Maintain traceability between sales, payment-category records,
  and SD reports; prevent duplicate processing and inconsistent financial updates.
- **Confirmed:** Complete Activity Logs access is reserved for Super Admin when implemented.
- **Proposed:** Require correction reasons where appropriate.
- **Unresolved:** Other mandatory-reason cases beyond the existing Received reversal requirement.

## 11. Reports and exports

- **Confirmed:** Generate operational sales summaries, category totals,
  reconciliation, and SD reports for daily, weekly, monthly, and custom ranges.
- **Confirmed:** Preserve information needed by staff and Finance; exact copies
  of existing Excel layouts are not required.
- **Confirmed:** Sales are based on recorded meal orders and their applicable
  prices, with corresponding recorded category totals. SD orders count toward
  sales when recorded and may appear in SD reports before actual payroll
  deduction. There is no payroll-processing or Finance-approval dependency.
- **Confirmed:** Received means internally paid; payment-category reports describe
  recorded transactions, not independently verified external payments. Totals
  do not prove physical cash receipt, verified GCash, or completed payroll SD.
  Broken SD formulas and masked zero results are not valid business controls.
  The legacy cash-plus-SD reconciliation is not an approved rule for all categories.
- **Proposed:** Clearly show periods/categories and trace totals to source transactions.
- **Proposed:** An internal mathematical consistency check may compare recorded
  order totals with corresponding category totals. Agreement does not verify
  external payments; no additional Finance or external-verification workflow is added.
- **Unresolved:** Official reporting/payroll cutoffs and range boundaries, columns,
  export formats, recipients, internal consistency details, finalization, submission,
  locking, and post-submission corrections.

## 12. Mock notifications

- **Confirmed:** A demo interface is optional. All notifications at this stage
  are mock/demo only: no real email/SMS or external provider connection.
- **Confirmed:** Clearly label demonstrations and never claim sent/delivered
  success for a message that was not sent.
- **Unresolved:** Future recipients, provider, and delivery workflow.

## 13. Security and data privacy

- **Confirmed:** Enforce backend authorization, deny access by default, and use
  verified actors. No shared/default credentials or pretend authentication.
- **Confirmed:** Core data/processing stays local/on-premises. Validate inputs
  and protect imports, reports, and audit access.
- **Confirmed:** Use synthetic or approved redacted development data. Do not
  expose employee PII, credentials, tokens, or secrets in logs, samples,
  documentation, or version control.
- **Confirmed:** Production use requires tested authentication, authorization,
  configuration/deployment safeguards, and verified backup/restore controls.

## 14. Known limitations and unresolved business questions

- **Confirmed limitation:** Prior review found 3,068 broken SD lookups masked as
  zero. Samples span different periods and do not establish a matched sales-to-payroll reconciliation.
- **Confirmed limitation:** All HRMS assigned-site values were blank. The CSV
  contained no explicit employment-status/SD-eligibility field; no additional
  eligibility restrictions are authorized.
- **Unresolved:** Approve the menu proposal; refine visitor fields/duplicate handling, organizational
  mapping/import conflicts, additional menu items, ranking details, price timing,
  overrides, and duplicate-order handling.
- **Unresolved:** Settle For Deposit, incentive/mixed categories, internal
  consistency/report details, and review responsibility.
- **Unresolved:** Refine remaining security/audit-view access, proposed correction reasons, report specifications,
  payroll cutoffs, and finalization/amendment rules before implementing them.

## 15. Acceptance criteria for a future implementation

These are future observable checks, not test results. Proposed criteria require
approval; unresolved details must be settled before affected checks can pass.

| ID | Status | Acceptance check |
| --- | --- | --- |
| AC-01 | Confirmed | Valid HRMS imports preserve employee numbers and record import history/results. Invalid structure, encoding, duplicate IDs, and malformed records are rejected or reported without silent loss or overwrite. |
| AC-02 | Confirmed | Successfully imported employees remain available without invented eligibility filters. Equal names/phone numbers do not merge employees. |
| AC-03 | Proposed | More frequently menu-selected dishes rank near the top of the appropriate dropdown. Sales quantities alone do not change ranking; reuse/tie rules await approval. |
| AC-04 | Proposed | A permitted administrator can add a missing dish, select an existing dish, and reuse a menu across dates without retyping dish names. |
| AC-05 | Confirmed | Dish/menu/category/price edits leave historical sale details and report amounts unchanged. |
| AC-06 | Confirmed | Quantity changes update line/order totals. The synthetic 2 vegetable + 1 non-vegetable + 3 extra rice order totals ₱220 at working prices. |
| AC-07 | Confirmed | Approved categories are recorded accurately; For Deposit is not selectable. Selection claims neither verified GCash nor completed SD. |
| AC-08 | Confirmed | Either role can select/reuse a visitor or create one within order entry. Visitor orders use Finance and remain separate from HRMS employees; name edits preserve stable identity and historical links, and names alone are not unique. Precise duplicate behavior remains unresolved. |
| AC-09 | Confirmed | All roles can mark Received; only Admin and Super Admin can reverse it. Marking records internally paid status without a separate Paid/Unpaid field, the accountable actor, and time. Corrections retain the original action and actor/time/order/action/before/after history. Other users cannot perform unauthorized changes. |
| AC-10 | Confirmed | Sales, category, reconciliation, and SD reports support daily/weekly/monthly/custom ranges with traceable totals. A recorded SD order counts without payroll processing and may appear in SD reporting before deduction; official cutoffs/internal consistency details remain to be agreed. |
| AC-11 | Confirmed | Mock notifications send no actual messages, connect to no provider, and display no false delivery success. |
| AC-12 | Confirmed | Logs, samples, and documentation expose no employee PII or credentials; backend checks deny unauthorized protected operations. |
| AC-13 | Confirmed | Each role uses an individual account. All roles perform routine operations; only Admin and Super Admin reverse Received. Only Super Admin manages users and will have complete Activity Logs access. |
| AC-14 | Confirmed | Important order, receipt, menu, visitor, import, and administrative user/role actions retain actor/time/record/action and applicable before/after values; corrections never erase the original audit history. |
| AC-15 | Proposed | If correction reasons are approved, require and retain them for the agreed correction cases. |

Next step: review with site staff and Finance, approve proposals and unresolved
financial/access rules, then plan implementation.
