# Database implementation plan — ASI Meal Management

## 1. Review status and current foundation

This is a reviewable plan, not approval to implement. Sources read:
[database proposal](database-design-proposal.md),
[business requirements](business-requirements.md),
[workflow discovery](business-workflow-discovery.md), root `AGENTS.md`, and
`README.md`. The latest owner decisions and database proposal take precedence
over older passages about sales on recording, single-method payments, and
Assistant Admin reversals. Those source documents are unchanged here.

**Confirmed/adopted:** One local/on-premises modular monolith; PostgreSQL;
HRMS CSV and employee-number identity without invented eligibility filters;
separate reusable visitors; retained menu categories; split allocations;
Received-only recognized sales/category/SD totals; Pending-first corrections;
Admin-only reversals; authenticated accountability and atomic audit history.
No site subsystem, external payment/payroll verification, separate Paid/Unpaid
status, refunds/cancellations, inventory, AI, or real notifications is added.

**Proposed** below means a technical recommendation or permission recommendation
awaiting approval. **Open** identifies a remaining business decision. Approval of
this plan and the proposal is required before writing models/migrations.

Inspection found only `asi_meal_api/main.py` with `/health`, an empty package
initializer, one health test, and pytest configuration. There are no mapped
models, session/engine setup, Alembic environment/revisions, or authentication.
`docs/adr/` contains no decisions. Existing requirements include SQLAlchemy,
Alembic, psycopg, FastAPI, pytest, and HTTP clients. Local installed metadata reports
SQLAlchemy 2.1.5, Alembic 1.20.0, psycopg 3.3.6, and pytest 9.1.1; requirements are
unpinned, so these are observations, not reproducibility guarantees. The API image
uses Python 3.13 and Compose proposes PostgreSQL 17 with a persistent volume.
That volume must never be used for disposable migration tests.
Future checks should run under the API's Python 3.13 runtime as well; record the
reviewed dependency set before migration implementation without changing it here.

## 2. Schema inventory and consistency review

The current proposal lists **17 application tables**, matching **17 distinct ER
entities**. Earlier conversational counts of 16 are obsolete. Alembic adds its own
`alembic_version` bookkeeping table; it is not an eighteenth application model.
Correction-reason options are a predefined configuration list, not another table.

| Finding | Planned treatment |
| --- | --- |
| `orders.menu_id` and `service_date` independently reference valid rows, but do not prove assignment or offering membership. | Validate under locks at creation; retain the recorded menu permanently in the initial version. Do not add a live composite FK that invalidates old orders after date reassignment. |
| Dish and offering categories are independent FKs. | Deliberate retained configuration: match at offering creation/explicit reclassification, not forever. No cascading synchronization. |
| Order total is not stored separately. | Generated line totals plus per-order sum; allocation equality is a cross-row invariant. |
| Received state and receipt/audit events can diverge if written independently. | One authorized transaction for all three; rollback/failure/concurrency tests. A normal FK alone cannot guarantee one event per transition. |
| Generic audit entity keys have no FK to every possible target. | Validate targets in the use case; typed receipt events have actual order/event FKs. |
| Login uniqueness was described both as UNIQUE and case-insensitive. | Use one named unique normalized-login index, not conflicting duplicate rules; do not apply login normalization to employee identifiers. |
| Snapshot category codes must remain meaningful. | Validate nonblank/known category codes at capture; do not FK sale snapshots to a dish's mutable category. Keep category codes stable rather than rename/delete referenced vocabulary. |
| Proposal allows nonnegative item prices but requires positive allocations. | Open zero-price handling: do not enable zero-total Received orders or invent a free-meal policy. Initial working prices are positive. Confirm before that case is supported. |

## 3. SQLAlchemy models, relationships, and creation order

**Proposed:** Use SQLAlchemy typed declarative mappings (`DeclarativeBase`,
`Mapped`, `mapped_column`, explicit `relationship`/`back_populates`), one metadata
registry, and a consistent naming convention for PK/FK/unique/check/index names.
Use a synchronous psycopg-backed engine/session initially; keep transaction
ownership in use cases, outside HTTP handlers and individual model methods.
No repository framework or speculative persistence abstraction is needed.

IDs are PostgreSQL bigint identities except the code/text/date/shared keys noted
below. Money is `Numeric(12,2)` handled with Python `Decimal`, never float;
timestamps are timezone-aware; audit payloads/issues are PostgreSQL JSONB.
Use database creation-time defaults, version 1, and Received=false. Receipt-change
and completion times remain null until those actions occur; set update times
explicitly on writes. Set actor fields from a verified server context, never a
default admin. Proposed order snapshots are `customer_name_snapshot` (required
text) and optional text `position_snapshot`, `campaign_snapshot`, and
`line_of_business_snapshot`; approve this minimal field list before freezing it.

This numbered table is the proposed initial migration creation order. Each model
maps to exactly one table; all referenced tables precede their dependents.

| # | Model / table | Key fields and FK relationships |
| --- | --- | --- |
| 1 | `Role` / `roles` | Text code PK: admin or assistant_admin; one role has many users. |
| 2 | `ItemCategory` / `item_categories` | Text code PK; display name and configurable default price; vegetable, non_vegetable, extra_rice. |
| 3 | `PaymentCategory` / `payment_categories` | Text code PK; cash, gcash, sd, incentive, finance. No For Deposit. |
| 4 | `User` / `users` | Role FK; login/display name, password hash, enabled flag, timestamps. No plaintext or default account. |
| 5 | `EmployeeImport` / `employee_imports` | Uploaded-by user FK; started/completed times, file hash, encoding/delimiter, processing/completed/failed status, inserted/updated/unchanged/rejected/total counts, optional file error code. |
| 6 | `Employee` / `employees` | Employee-number text PK; last-import FK; name and approved organizational fields. No eligibility filter or mandatory site. |
| 7 | `EmployeeImportRow` / `employee_import_rows` | Import FK; optional employee FK for accepted/matched records; row number, outcome, privacy-safe issues. Import has many row results. |
| 8 | `Visitor` / `visitors` | Stable bigint ID, non-unique display name, created-by user FK, timestamps. Separate from Employee. |
| 9 | `Dish` / `dishes` | Category FK; name, active flag, timestamps; many configured menu offerings. |
| 10 | `Menu` / `menus` | Created-by user FK; label/timestamps; many dates and offerings. |
| 11 | `MenuDate` / `menu_dates` | Service-date PK; menu FK; many orders can reference a date. |
| 12 | `MenuItem` / `menu_items` | Menu, dish, and category FKs; configured name/category/price; source for many order lines. |
| 13 | `Order` / `orders` | MenuDate and recorded Menu FKs; exactly one Employee or Visitor FK; creator and receipt-changed user FKs; UUID request key, recorded time, report/customer snapshots, Received flag, receipt-change time, version. |
| 14 | `OrderItem` / `order_items` | Order and source MenuItem FKs; line number, name/category/price snapshots, quantity, generated stored line total. |
| 15 | `PaymentAllocation` / `payment_allocations` | Order, payment-category, created-by and updated-by user FKs; positive amount/timestamps. Order has many allocations, including a single-method row. |
| 16 | `AuditEvent` / `audit_events` | Actor user FK; time/action/entity type/key, allowlisted before/after JSONB, optional general reason. Append-only history. |
| 17 | `ReceiptEvent` / `receipt_events` | Audit-event PK/FK and order FK; previous/new booleans, correction code/label snapshot and optional explanation. Audit event has at most one typed receipt event. |

Specify `foreign_keys` explicitly for relationships with multiple links to User
and for employee/import paths. Collection relationships must not imply cascading
deletion of financial/history data. Generated `OrderItem.line_total` is read-only
to callers. Totals are query expressions, not mutable counters or another model.
The nullable customer FKs express alternatives; a CHECK enforces exactly one.
Use passive deletion handling for restrictive parent relationships so the ORM
does not silently null child references before the database can enforce RESTRICT.

## 4. Constraints, indexes, and deletion behavior

**Proposed database checks:**

- Required columns receive NOT NULL independently of CHECK constraints; a CHECK
  that evaluates to SQL NULL does not by itself reject missing required data.
- Nonblank identifiers/names/codes; named allowed-code constraints for roles,
  category vocabulary and import statuses/outcomes. Employee identifiers remain
  text without invented fixed lengths/case rules.
- Quantities/line numbers > 0; prices >= 0; allocations > 0; all monetary values
  finite and within precision. Reject excess decimal precision at the boundary
  before PostgreSQL could silently round it. No new rounding policy is approved.
- Employee/visitor XOR; positive order version; paired receipt actor/time;
  Received=true requires both. A reversed order can retain its latest actor/time.
- Receipt from/to must differ; correction reason code/label nonblank together,
  and code `other` requires a trimmed non-empty explanation. Initial marking has
  no invented correction reason; audit action distinguishes it from correction.
- Nonnegative import counters, positive CSV row numbers, paired completion/status
  rules, and approved row outcomes. Reconcile counts to outcomes in the import
  completion transaction; file failures may have no row results.

**Uniqueness/index plan:** PKs cover identifiers. Add unique request key, normalized
login, menu/dish, order/line number, order/payment category, and import/row number.
Do not make employee names, visitor names, phone numbers, or employee/date pairs
unique. Multiple intentional orders remain possible. Duplicate method inputs
should be consolidated to the one allocation row for that category.

Retain the proposal's indexes: Received orders by service date/ID (partial index),
employee/date and visitor/date histories, menu-date by menu, menu-item by dish,
receipt history by order/event, and audit entity/type/key/time. Unique composite
indexes cover line/allocation/import lookups; do not duplicate them. Add an
allocation category/order index only if SD/category query plans justify it.

**Deletion:** Use explicit restrictive FKs and no ORM `delete`/`delete-orphan`
cascades on history or master records. Disable accounts/dishes rather than delete
referenced rows. Employees absent from imports remain. No order-delete, refund,
cancellation, visitor merge, or report-locking functionality is implied. Permitted
Pending line/allocation removal is an explicit audited operation, not an ORM
side effect. Record removed identifiers/values in audit history.

**Cross-row enforcement boundary:** Ordinary CHECKs cannot enforce nonempty
orders, allocation sums, visitor-Finance allocation rules, or menu membership.
Recommend narrow deferred constraint triggers for committed nonempty orders,
visitor allocations all Finance, and Received orders having allocations whose
sum equals the line-total sum. Check both affected parents if a child can move;
prefer to prohibit child reparenting. Every item/allocation writer must first
lock its order, including updates/removals; trigger validation must follow the
same lock discipline. Test concurrent writers explicitly.

Recommend an immediate guard on item/allocation writes to reject changes while
Received, complementing backend checks. Financial aggregate checks are deferred
until commit so creating/rebalancing lines is possible within one transaction.
These triggers are proposed technical safeguards, not new payment verification
or additional business statuses. Review them explicitly in the initial migration;
do not claim autogeneration will produce them. Authorization and verified human
actor attribution remain backend responsibilities, not guaranteed by these triggers.

## 5. Recommended Pending edit permissions

**Recommendation requiring owner approval:** Permit both roles to do normal
entry work on shared Pending orders. Do not invent site or creator-only access.
The model/migration need no new permissions table; use an explicit backend matrix.
The following is a field-level recommendation, not a new confirmed policy.

| Action/field | Admin | Assistant Admin | Boundary |
| --- | --- | --- | --- |
| Create order: employee/visitor, assigned date/menu, items, allocations | Allow | Allow | Validate once on creation; server resolves menu and snapshots. |
| Change quantity on an existing Pending line | Recommend allow | Recommend allow | Preserve its recorded unit price/name/category; recalculate line total. |
| Add/replace a Pending line from the recorded menu | Recommend allow | Recommend allow | Server validates source; capture the selected offering's values for the new line, never silently reprice untouched lines. |
| Remove a Pending line | Recommend allow | Recommend allow | Final committed order retains at least one line; audit removal. |
| Add/change/remove Pending allocation category or amount | Recommend allow | Recommend allow | Approved categories, positive amounts, Finance-only visitor allocations; balanced before Received under proposed timing. |
| Edit employee/visitor identity or customer snapshot fields after creation | Disabled pending rules | Disabled pending rules | Admin status does not authorize an undefined sensitive change. |
| Edit service date, recorded menu, or reparent existing source lines | Disabled pending rules | Disabled pending rules | No silent historical reassignment; future validated/audited feature only. |
| Manually change recorded dish name/category/unit price or line total | Disabled pending rules | Disabled pending rules | No arbitrary price override or client-written generated total. Catalog/menu management is a separate operation. |
| Edit creator, timestamps, request key, version, audit or reason history | Never directly editable | Never directly editable | Server-managed metadata; immutable audit history. |
| Mark Pending order Received | Allow (adopted) | Allow (adopted) | Authenticated actor, consistency validation, atomic event. |
| Reverse Received to Pending | Allow (adopted) | Deny (adopted) | Confirmed reason/checkbox safeguards; backend enforcement. |
| Edit items/allocations while Received | Deny | Deny | Admin reverses first, then only approved Pending fields may change. |

Snapshot changes are allowed only for explicitly selected/replaced lines if that
recommendation is approved; previous snapshots remain in the edit audit. This is
different from a catalog update retroactively changing every order. Proposed
menu-line replacement needs approval before enabling it. New-line price comes
from the offering at edit time; approve this detail rather than guessing it.
The predefined reason/checkbox requirements already apply to receipt corrections;
whether to require them for Pending detail edits remains open. Important Pending
edits are always audited even if no extra reason interaction is approved.

## 6. Transaction plan and historical provenance

**Order creation:** Obtain the authenticated actor from a verified server context;
do not wire protected operations to unimplemented/pretend authentication. Start
one transaction, lock the service-date assignment against reassignment/deletion,
resolve its menu, and lock that menu/selected offerings against changes. Validate
each selected offering belongs to the assigned menu, copy item/customer snapshots,
and save order, lines, allocations, and audit together. Reject missing assignment,
wrong-menu offerings, invalid customers, or invalid values without partial saves.
Use consistent date → menu → offering lock order for menu writers too. Validate
request-key retry payloads: return the original only for the same request content;
do not silently treat a different order as a retry.

**Existing-order provenance:** `orders.menu_id` records the validated menu at
recording; it is not recomputed from today's `menu_dates` assignment. Restrict
source offerings from moving between menus after reference (copy instead), using
backend validation plus a narrow update guard if required. Routine Pending edits
use the recorded menu even if the date is later assigned a different menu. Lock
the order and its recorded menu/offerings; do not overwrite its original menu/date.
Received re-marking validates existing snapshots/allocations, not current catalog
prices. Preserve original receipt events through all corrections.

**Future date/menu change:** Unsupported initially. It would need approved field
permissions, an explicit action on a Pending order, transactional validation of
the target date/menu/every selected item under locks, and before/after audit of
date, menu, source links, affected snapshots, and totals. Never implement it as
a bulk FK update or automatic response to menu reassignment. Existing history
must remain readable. No workflow for this feature is authorized by this plan.

**Catalog/menu edits:** Initialize offering category from the selected dish;
retain existing configured categories after catalog reclassification. Show
differences for review. Explicit offering reclassification requires matching the
current dish category and an explicit permitted price choice, with audit. No
composite dish/category FK forcing permanent equality. Lock dish/offering writes
consistently; order snapshots remain unchanged. Menu reuse/frequency is derived
from menu selections, not sold quantities; exact counting/ties still need approval.

**Pending edits:** Lock the parent order, check expected version and current
Pending state, validate permitted fields, save the complete change plus audit,
increment version, and commit together. No partial commits per line/allocation.
This serializes edits against receipt changes; stale requests fail for review.

**Received transitions:** Both roles can mark; only Admin can reverse. Resolve
actor from the server session, check role, reason/Other explanation/checkbox for
corrections, lock the order, and check version and actual old state. Save new
state, actor/time/version, AuditEvent, and ReceiptEvent in one transaction. On
failure roll back everything; a retry that requests the current state does not
fabricate a transition. Do not require payment evidence or a Finance approval.

## 7. Audit, correction reasons, and import history

Typed receipt events retain the FK-linked authenticated actor/time/action from
AuditEvent plus order, from/to status, stable reason code, saved reason label,
and explanation. Keep the five confirmed options: Mistaken click; Incorrect
employee marked; Incorrect order marked; Incorrect order details; Other reason.
Use the proposal's stable codes and a simple predefined server-side list, not a
settings subsystem. Trim Other explanation and reject blank text. Historical
labels remain intact when options are renamed/retired; no live-list FK or mutable
enum should invalidate old reason history. The checkbox uses the authenticated
display name; the browser-supplied name is never identity proof.

General audit entries identify type/key/action with allowlisted before/after
values. For receipts the typed reason is authoritative; any summary must agree.
Append-only privileges must use a separate runtime DB identity from the migration
owner; ORM conventions alone do not prohibit audit UPDATE/DELETE. Restrict audit
access and exclude credentials/password hashes, raw CSV, unnecessary contact
details, and personal values in routine logs. Minimal protected identity/history
needed by actual reports is not public diagnostic data.

**Import plan:** Create the job first, validate file/header/encoding/delimiter,
then process rows using employee number. Distinguish inserted, updated, unchanged,
and rejected. Do not choose an arbitrary winner among duplicate identifiers;
recommend reporting all conflicting input rows, subject to policy approval.
Store row number and field/error codes without raw invalid values. Fatal file
errors are job errors; absent employees are retained, not deactivated. HRMS-owned
values update only through the approved mapping/blank policy; do not correct a
campaign by guessing locally or add eligibility tests unsupported by the export.

Apply accepted employees, row results, counts, completion state and audit atomically;
on failure roll back employee updates and separately record job failure. Serialize
imports to avoid lost updates. A repeated file hash supports review, not a unique
ban on intentional retries. Partial acceptance versus whole-file rejection and
import-role authority need approval before enabling the importer.

## 8. Initial Alembic migration plan

**Proposed future files:** Small persistence base/session modules, focused model
modules under the existing API package, an Alembic environment/templates/revisions,
and focused PostgreSQL integration tests. Exact file layout can follow the real
use cases; no new application layer or frontend change is required. None is
created by this planning task.

1. After approval, register all 17 models in one metadata registry. Configure
   Alembic to read that metadata and an externally supplied disposable connection
   URL; never import/run the FastAPI app or connect during module import. Never
   put credentials in revision files, committed configuration, or test output.
2. Generate an initial candidate revision against an empty disposable PostgreSQL
   17 instance. Review every table/column/default/nullability/FK, the dependency
   order above, generated Decimal line totals, named checks/uniques/indexes, and
   the downgrade. Hand-review trigger definitions and partial/expression indexes;
   autogeneration is not proof of correctness and does not infer business rules.
3. Use one transactional schema revision for the 17 tables, required indexes,
   and agreed narrow integrity triggers. Downgrade removes dependent triggers
   first, then indexes/tables in reverse creation order. Audit application users
   never receive this downgrade capability. No destructive migration is run
   against any existing project database.
4. Prefer a separate small reference-data revision for approved two role codes,
   three item categories with working prices (₱50/₱75 including rice, ₱15 extra
   rice), and five payment categories. No employee/user account, password, sample
   order, or For Deposit row. This keeps reference-data changes reviewable; future
   revisions must not silently reset configurable prices. Correction reasons stay
   in the predefined list. Confirm exact codes before this revision is approved.
5. Review migration and runtime privilege separation before deployment. Do not
   autostart migrations during app startup or let `create_all` replace migrations.
   Scope grants appropriately; never rely on a privileged schema owner as runtime.

## 9. Disposable PostgreSQL verification and acceptance

These are future tests, **not run in this documentation task**. Use PostgreSQL 17,
not SQLite, for checks involving JSONB, numeric behavior, generated columns,
partial indexes, row locks, triggers, and transactional DDL. Provision a separately
named temporary instance/database with generated local credentials and a test-only
DSN. Explicitly verify its identity/empty state before upgrade or downgrade.
Never attach Compose's existing `postgres_data` volume. Clean up only the test
resources created by the test harness; do not delete unrelated containers/volumes.

Use fictional employees/visitors and individually identified synthetic actors;
permission test actors are explicit fixtures, not a production authentication
substitute or default shared account. Test rows are separate from migration data.

| Test group | Required acceptance evidence |
| --- | --- |
| Upgrade and metadata | Empty DB upgrades to head; exactly 17 application tables plus Alembic bookkeeping. Inspect actual PK/FK/check/unique/index/trigger definitions and generated totals; metadata/revision comparison has no unexplained drift. ORM mappers configure without ambiguous User/import relationships. |
| Migration lifecycle | With synthetic data, downgrade only the verified disposable DB to base and upgrade again; no orphan objects. Applying head again is a no-op; reference categories/prices are correct and no accounts/PII are seeded. |
| Keys, constraints, deletion | DB tests reject duplicate IDs/login/request keys, bad FKs, customer XOR violations, invalid role/category/outcome, negative/nonfinite money, zero quantities, mismatched receipt metadata, empty committed orders, and unsafe parent deletes. Boundary tests reject excess decimal precision before typed numeric storage can round it. Identical visitor names and multiple intentional same-day orders remain possible. |
| Menu/category provenance | Reject missing-date/wrong-menu creation. A two-connection date reassignment or offering edit blocks until creation commits or is rejected on retry; never saves a mixed source. Catalog reclassification retains offerings; explicit offering changes require price confirmation. Old order menu/snapshots remain unchanged after date/menu/dish edits or HRMS/visitor name updates. |
| Split and totals | Synthetic 1 vegetable + 2 non-vegetable + 3 rice totals ₱245; GCash ₱200 + Cash ₱45 balances. Reject nonpositive/invalid allocations, invalid visitor methods, and imbalance at Received. Recognized sales = ₱245 once; category totals = ₱200/₱45, not twice the order or an item × allocation product. |
| Receipt and permissions | Pending contributes zero; mark includes once; Admin reversal excludes; re-mark restores once for sales/categories/SD. Assistant reversal and both-role Received edits fail. Unapproved identity/date/menu/price edits fail. Concurrent mark/edit/reversal and stale versions cannot lose history or bypass invariants. |
| Audit and reasons | Inject failure between status/data and audit inserts; all roll back. Every actual receipt transition has matching actor/order/time/before/after and applicable reason. Blank/whitespace Other or unchecked acknowledgement fails; forged browser identity is ignored/rejected. Reason-list renames leave old labels intact; runtime audit mutation is denied. |
| HRMS import | Synthetic valid/invalid/duplicate/missing-field/encoding/row-width files produce safe counts/results under the approved policy. Updates retain employee numbers, absent employees and sale snapshots; failure leaves no partial updates. No PII/raw rows/secrets appear in diagnostic logs. |
| Reporting | Daily/weekly/monthly/custom tests use approved boundaries and the same current Received population. Mixed SD reports sum only SD allocations, without payroll checks. Pending subtotals are separate and reversal/re-marking does not accumulate counters. No claim of external payment verification. |

Run the existing health test as a regression check after future implementation,
plus new model/migration/transaction/permission/report tests. A passing health
test alone cannot validate persistence. Do not claim running-app or production
readiness from unit tests or migration upgrade alone.

## 10. Open decisions and what they block

| Decision requiring input | Impact / safe interim boundary |
| --- | --- |
| Approve proposal, technical enforcement choices, and this plan | Blocks any model/migration implementation; this task provides no implementation authorization. |
| Approve the recommended Pending edit matrix | Blocks enabling those edits; schema/migration can proceed after overall approval with sensitive fields disabled. Identity/date/menu/manual snapshot-price changes stay unsupported until explicitly defined. |
| Confirm protected customer/organizational snapshot fields and visitor minimum fields | Blocks freezing the exact initial column list for relevant models; recommend employee number/name plus necessary approved report organization, visitor stable ID/name only. No contact data by default. |
| Zero-price/zero-total behavior and exact allocation-completion timing | Blocks those edge cases/receipt validation policy, not positive-price schema checks. Recommend positive working-price use only and balance at Received; no free/receivables policy is invented. |
| HRMS required fields, mappings, blank updates, duplicate handling, partial acceptance and import permission | Blocks the live importer, not its history tables. Do not import real records to resolve these choices. |
| Catalog reclassification/price override authority; menu frequency/reuse counting and legacy items | Blocks those actions or ranking behavior, not basic retained-category storage. Manual historical price overrides remain disabled. |
| Report-date basis, week/payroll cutoffs, columns/formats/submission | Blocks final report acceptance, not core Received/split data integrity. Service-date basis is proposed, not an approved cutoff policy. |
| Assistant audit access, remaining security settings, secure first-Admin/session provisioning | Blocks affected protected operations or live deployment; deny undefined sensitive permissions. Admin-only reversals are already adopted, not an open initial decision. |
| For Deposit; finalized-period locking/adjustments; future notification delivery | Can remain open: exclude For Deposit; no locks/adjustments or real delivery. No extra tables/features are needed now. |

## 11. Smallest sensible implementation sequence

Each stage is a future reviewable change; stop at its acceptance gate before the
next. No stage is executed by this document.

1. **Approve the plan and schema column decisions.** Agree technical constraints,
   minimum stored employee/visitor/report fields, and safe disabled operations.
   Acceptance: one unambiguous 17-table inventory and recorded unresolved gates.
2. **Implement mappings and initial migrations only.** One metadata registry,
   deterministic table/dependency order, schema plus small reference-data revisions,
   and disposable PostgreSQL upgrade/downgrade/constraint tests. Acceptance: verified
   actual schema, no migration drift, no business/employee/account data seeded.
3. **Implement minimal persistence use cases and transaction tests.** In order:
   menu/date/provenance and order creation; approved Pending edits with audit;
   split allocations and receipt transitions. Acceptance: authorization matrix,
   consistency, atomic rollback, history, concurrency, and no duplicate totals.
   Protected HTTP exposure waits for real authenticated actor integration.
4. **Implement the validated employee importer after its policy approval.**
   Acceptance: safe row/job history, approved updates, retention and rollback tests.
   Synthetic fixtures support earlier order tests without importing real data.
5. **Add report queries after period/output decisions.** Acceptance: current
   Received sales/category/SD results, correct split aggregation, stable historical
   snapshots, and regression tests. No payroll processing or locked-report feature.

The immediate next step is owner review and explicit approval, not code generation.
