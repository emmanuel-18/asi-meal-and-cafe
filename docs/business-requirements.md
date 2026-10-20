# ASI Meal Management — Business requirements

Status: documentation for review, not implemented application behavior. Sources:
the owner's latest clarifications, root `AGENTS.md` and `README.md`, and the
reference review in [Business workflow discovery](business-workflow-discovery.md).

**Confirmed** means an explicit owner requirement or existing project constraint.
**Proposed** means a recommendation awaiting approval. **Unresolved** means a
business decision is still required. Proposals are not approved implementation
specifications or a final permission matrix.

## 1. Purpose and business objectives

- **Confirmed:** Reduce repeated paper-to-Excel work and improve order entry,
  receipt tracking, reconciliation, and reporting for staff and Finance.
- **Confirmed:** Keep the workflow fast, simple, and usable on desktop, tablet,
  and mobile.

## 2. Users and proposed roles

| Status | Role concept | Intended responsibility |
| --- | --- | --- |
| Proposed | Administrator | Routine permitted order and menu management. |
| Proposed | Supervisor / designated privileged role | Sensitive corrections, such as reversing Received. |
| Proposed | Monitoring role | Read-only access to permitted records and reports. |

- **Proposed:** Clearly define permissions by role or make them configurable,
  without unnecessarily restricting ordinary administrative work.
- **Unresolved:** Exact names, number of roles, site/record access, import/report
  privileges, and action-level permissions. Not all administrators need identical
  permissions.

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
- **Proposed:** Initially show fictional choices Visitor A, Visitor B, Visitor C.
- **Confirmed:** Visitor meals are currently associated with Finance.
- **Unresolved:** Generic visitor placeholders versus reusable records for actual
  individual visitors. No final visitor identity design is approved.

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
  and how each category contributes to reconciliation.

## 9. Receipt tracking and corrections

- **Confirmed:** Record the category with the order. The owner states that an
  employee pays before receiving the meal; staff mark Received on handover.
- **Confirmed:** No separate Paid/Unpaid workflow initially unless later discovery
  establishes a need.
- **Confirmed:** Authorized staff must be able to undo an incorrect Received mark
  while retaining its history.
- **Proposed:** Apply role-based authority and audit logging; a supervisor or
  designated privileged role handles sensitive reversals.
- **Unresolved:** Exact permissions and mandatory-reason cases, other order
  corrections, refunds/cancellations, and what payment before handover means for
  SD, Incentive, and Finance. Received must not imply completed payroll deduction.

## 10. Audit logging

- **Confirmed:** Consequential corrections retain verified actor, timestamp,
  affected record, previous/new values, and reason where required. Never silently
  erase correction history.
- **Confirmed:** Maintain traceability between sales, payment-category records,
  and SD reports; prevent duplicate processing and inconsistent financial updates.
- **Unresolved:** Exact reason requirements and access to audit records.

## 11. Reports and exports

- **Confirmed:** Generate operational sales summaries, category totals,
  reconciliation, and SD reports for daily, weekly, monthly, and custom ranges.
- **Confirmed:** Preserve information needed by staff and Finance; exact copies
  of existing Excel layouts are not required.
- **Confirmed:** Totals do not prove actual payments or completed payroll SD.
  Broken SD formulas and masked zero results are not valid business controls.
  The legacy cash-plus-SD reconciliation is not an approved rule for all categories.
- **Proposed:** Clearly show periods/categories and trace totals to source transactions.
- **Unresolved:** Official reporting/payroll cutoffs and range boundaries, columns,
  export formats, recipients, full reconciliation logic, finalization, submission,
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
- **Unresolved:** Approve the menu proposal, visitor identity, organizational
  mapping/import conflicts, additional menu items, ranking details, price timing,
  overrides, and duplicate-order handling.
- **Unresolved:** Settle For Deposit, incentive/mixed categories, category-specific
  handover expectations, complete reconciliation, and review responsibility.
- **Unresolved:** Approve roles, correction reasons, report specifications,
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
| AC-08 | Confirmed | Visitor orders are separate from HRMS employees and associated with Finance; final identity behavior awaits its business decision. |
| AC-09 | Confirmed | Received can be marked and corrected only with applicable authority. Unauthorized reversals fail; permitted reversals retain actor/time/record/before/after and required reasons. The exact matrix/reason rules await approval. |
| AC-10 | Confirmed | Sales, category, reconciliation, and SD reports support daily/weekly/monthly/custom ranges with traceable totals; official cutoffs and reconciliation definitions must be approved before validating results. |
| AC-11 | Confirmed | Mock notifications send no actual messages, connect to no provider, and display no false delivery success. |
| AC-12 | Confirmed | Logs, samples, and documentation expose no employee PII or credentials; backend checks deny unauthorized protected operations. |

Next step: review with site staff and Finance, approve proposals and unresolved
financial/access rules, then plan implementation.
