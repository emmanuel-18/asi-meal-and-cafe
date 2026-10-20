# Business workflow discovery

This update combines the reference review already completed in this conversation
with the business owner's subsequent clarifications. Reference files were not
reanalyzed for this update. See [Business requirements](business-requirements.md)
for future behavior and acceptance criteria.

**Confirmed** identifies an owner-confirmed rule or an observed fact with its
source stated. **Inferred** identifies an interpretation requiring confirmation.
**Proposed** identifies a future approach awaiting approval. **Unresolved** means
more information is needed. Spreadsheet behavior is not automatically policy.

## Workflow and confirmed direction

1. **Identify and collect orders — Confirmed, alignment notes:** Site admins
   collect orders through morning rounds or chat and record names and
   organizational details in a paper logbook. **Confirmed, owner:** The app will
   identify employees by employee number from HRMS CSV, retain all successfully
   imported employees, and impose no additional eligibility restrictions.
2. **Select meals — Confirmed, owner:** Current working prices are vegetable
   meal **₱50 including rice**, non-vegetable meal **₱75 including rice**, and
   extra rice **₱15**. These replace the earlier without/with-rice description.
   Prices must be configurable and historical sale details preserved.
   **Proposed:** Reuse a dish catalog, with vegetable/non-vegetable dropdowns,
   add-new-dish capability, and menus for one or multiple dates. Rank dishes by
   menu-selection frequency, not meals sold; support daily or repeated menus.
3. **Record order and category — Confirmed, owner:** Transactions support
   multiple items and quantities with automatic totals. Staff record Cash,
   GCash, Salary Deduction (SD), Incentive (voucher/gift card), or Finance.
   Visitor meals are separate from HRMS employees and associated with Finance.
   **Unresolved:** Generic visitor placeholders versus reusable individual records.
4. **Hand over meal — Confirmed:** Notes describe signatures on receipt, usually
   at lunch. The owner confirms payment before handover and staff marking
   Received when handed over. No separate Paid/Unpaid workflow is required
   initially. Category selection is administrative and proves neither a GCash
   transfer nor completed SD. **Unresolved:** What payment-before-handover means
   for SD, Incentive, and Finance.
5. **Prepare daily totals — Confirmed, records:** Staff transcribe paper orders
   into Excel. Quantities and payment labels are manual inputs; formulas compute
   employee-day amounts, item revenue, and category totals.
6. **Reconcile — Confirmed, records:** The main sheet compares cash plus SD with
   item revenue, omitting other displayed categories. This is not an approved
   general reconciliation rule. **Unresolved:** Cash counting, external evidence,
   reviewers, discrepancy handling, and treatment of all categories.
7. **Consolidate and report — Confirmed:** Notes describe weekly consolidation;
   an employee-by-date SD template exists, but broken lookups prevent validation.
   The owner requires daily, weekly, monthly, and custom-range reports, preserving
   staff/Finance information rather than necessarily copying Excel layouts.
8. **Correct mistakes — Confirmed, owner:** An incorrect Received mark must be
   reversible without erasing history. **Proposed:** Role-based permissions and
   audit logging, with a privileged role for sensitive corrections. Exact
   permissions and other correction rules remain **Unresolved**.

## Evidence and open questions

| Area | Evidence / conclusion | Unresolved questions |
| --- | --- | --- |
| Employees | Owner confirms HRMS CSV and employee-number identity. No invented eligibility filter. | Required import fields, organizational/site mapping, refresh and update/conflict handling. |
| Menu | Owner confirms category prices including rice. Records also show hotsilog/cornsilog. | Are those legacy items still needed? Menu ranking counting/ties; price effective dates and overrides. |
| Orders | Owner confirms multi-item quantities; workbook aggregates by employee-day. | Separate versus combined orders; duplicate handling. |
| Visitors | Owner associates meals with Finance. Placeholder choices may initially be used. | Generic placeholders versus reusable individual identities. |
| Categories | Owner confirms Cash, GCash, SD, Incentive, Finance. | For Deposit; mixed categories; incentive redemption and category-specific handover evidence. |
| Receipt/corrections | Owner confirms Received and reversibility with retained history. | Exact role authority and mandatory correction reasons; other amendments. |
| Reconciliation | Sample arithmetic agrees; this is not proof of actual money received. | Full category treatment, evidence, reviewers, and discrepancy handling. |
| Reports/SD | Reporting ranges confirmed; broken SD results are not reliable. | Official cutoffs, columns/formats, recipients, submission, finalization, locking, and later corrections. |

## Reference files previously inspected

All five files are under `ASIMEAL/`; none were modified. No employee PII is
reproduced. The earlier statement that records were missing is superseded.

| Source | Findings retained from prior review |
| --- | --- |
| `Project ALignment and Buddy Up minutes notes.txt` | Site admins collect orders, obtain receipt signatures, transcribe paper records, and consolidate weekly. Tablet/phone/laptop use requested. Older price wording is superseded above. |
| `Sales Logbook.jpg` | October 13, 2026. Columns: number, name, campaign, named meal, extra rice, amount, mode of payment, Received By. Circles, checkmarks, signatures, and blanks require convention clarification. |
| `Daily sales summary, reconcilliation and Sales Deduction Report.xlsx` — Sheet 1, `daily sales` | October 1–9, 2026 date blocks; employee name/campaign/position, quantities, calculated amounts, payment labels. Formula prices: 50, 75, 15, 70, 75. Quantity × price calculations matched saved employee-day amounts. Final reconciliation adds Cash and SD only; GCash/Finance were zero in this sample. |
| Same workbook — Sheet 2, `Salary deduction list` | 236 employee rows with selected September 16–30 dates and totals. 3,068 lookups contain `#REF!` masked by `IFERROR(...,0)`. Zero totals must not be treated as valid SD results. Title incorrectly says September 16–31. No Sheet 3 or later was inspected. |
| `sales perday per mode of payment.xlsx` | September 1–15, 2026. Manual daily Cash, G Cash, SD, Incentive, Finance, For Deposit amounts. Daily formulas add six categories; period breakdown omits Incentive (zero in sample). Possible category overlap is unresolved. |
| `HRMS employee export].csv` | UTF-8 BOM, comma delimiter; 1,225 records with ten fields. No missing/duplicate employee numbers. All assigned-site values blank. Names/phone numbers must not be application identifiers. |

**Inferred:** Direct order entry and report generation could remove repeated
transcription. Detailed sales campaign labels may correspond to HRMS line of
business rather than HRMS campaign; mapping needs confirmation.

Samples cover different periods and cannot establish a matching end-to-end
reconciliation. A valid SD source, payment verification procedure, payroll handoff
and completion evidence, and approved correction procedure remain unestablished.

## Decisions needed before implementation

- Approve menu workflow, visitor identity, import mappings/conflict handling, and legacy item scope.
- Clarify payment-before-handover by category without treating Received as payroll completion.
- Settle For Deposit, full reconciliation, report specifications, and payroll cutoffs.
- Approve role permissions, correction reasons, report finalization, and later amendments.

## Next step

Review the linked requirements with site staff and Finance. Walk through a
matching day and SD period using valid source records, then approve remaining
business rules before database or feature design. Core processing stays
local/on-premises; no inventory, AI, direct HRMS API, real notifications, or
external payment processing is introduced.
