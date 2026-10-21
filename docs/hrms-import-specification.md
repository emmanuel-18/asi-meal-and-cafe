# HRMS employee CSV import specification

Status: Version 1 contract, with the Stage 3B owner decisions below adopted.
The requested Version 1 behavior below follows the existing
[business requirements](business-requirements.md),
[database proposal](database-design-proposal.md),
[implementation plan](database-implementation-plan.md), root `AGENTS.md`, and
[backend foundation](../apps/api/DATABASE.md). Remaining live-use decisions are listed last.

Stage 3B adopts whole-file rejection, blank optional-value retention and
**Admin-only execution**. These latest decisions replace earlier approval gates
and the database proposal's partial-acceptance recommendation. Header matching
remains exact by name, with only the optional UTF-8 BOM removed; no aliases or
case/whitespace guesses are added. The implementation remains service-only.

## 1. Source and exact field mapping

Only the header of `ASIMEAL/HRMS employee export].csv` was inspected for this
specification, stopping before the first employee record. It contains these ten
headers in this order. No exporter implementation was found in this workspace;
the header establishes the expected structure, not validation of employee values.

| CSV column | Treatment | Destination / requirement |
| --- | --- | --- |
| `employee_number` | Import | `employees.employee_number`; required text identity. |
| `full_name` | Import | `employees.full_name`; required nonblank name. |
| `position` | Import | `employees.position`; optional value. |
| `campaign` | Import | `employees.campaign`; optional value. |
| `line_of_business` | Import | `employees.line_of_business`; optional value. |
| `assigned_site` | Ignore | No site subsystem or eligibility rule. |
| `email_address` | Ignore | No approved contact-data requirement. |
| `primary_contact_number` | Ignore | No approved contact-data requirement. |
| `alternative_contact_number` | Ignore | No approved contact-data requirement. |
| `alternative_contact_number_2` | Ignore | No approved contact-data requirement. |

Map organizational fields by their exact header names; do not swap campaign and
line of business to imitate legacy report labels. Ignored values are parsed only
as necessary for CSV structure, then discarded; never persist or log them. They
need no email/phone validation. Contact storage requires separate approval.

## 2. Validation contract

Recommended technical contract for the existing ten-column exporter:

- Decode strictly as UTF-8, accepting an optional leading BOM (`utf-8-sig`);
  never replace undecodable bytes or guess another encoding. Use comma-delimited
  CSV with double-quote escaping, including correctly quoted commas/newlines.
- Require exactly the ten unique header names above; order may differ because
  mapping is by name. Reject missing, repeated or unexpected headers. Even ignored
  headers identify this export format; their cell values may be empty. Do not
  silently rename, case-fold, or trim headers beyond removing the leading BOM.
- Every data record must have ten cells. Reject malformed quoting, incorrect row
  width, NUL characters in mapped text, and blank data records. A normal final
  newline creates no extra record. Reject an empty/header-only export as
  `EMPTY_EXPORT`; it must never clear the directory.
- Preserve employee numbers as text, including leading zeros and letter case.
  Reject missing/whitespace-only identifiers and surrounding whitespace instead
  of silently changing identity. Do not infer numeric formats or merge by name.
- Trim surrounding whitespace from names and optional mapped fields; preserve
  internal text, spelling, accents and case. A trimmed empty name is invalid.
  Trimmed empty optional values follow section 3. Apply the same comparison rules
  to new and existing values; do not silently normalize existing identifiers.
- Detect duplicate employee numbers across the entire file using exact identity
  comparison. Report **every occurrence**, including the first, even when values
  are identical. Never choose the first/last occurrence as the winner.
- Do not infer employment status, SD eligibility, deactivation, or access rules:
  this export has no approved employment-status/eligibility field.

## 3. Insert, update and unchanged behavior

HRMS remains the source of truth for the five mapped fields. The importer must
apply only this explicit mapping; no arbitrary employee-field updates are allowed.

| Existing employee | Incoming approved values | Outcome |
| --- | --- | --- |
| No matching employee number | Valid required values | Insert employee; empty optional values become SQL NULL. |
| Matching number | At least one effective mapped value differs | Update only changed HRMS-managed fields. |
| Matching number | All effective values equal | Unchanged; do not write the employee row. |
| Employee absent from export | No incoming record | Retain unchanged; no deletion, deactivation or eligibility change. |

**Adopted Version 1 policy:** A blank optional source value
retains an existing nonblank value. If both are empty, retain the current empty
value. A nonblank incoming value replaces a different existing value. Apply this
rule before deciding updated versus unchanged. This can retain stale HRMS data;
it is not an approved mechanism for explicitly clearing a field. Required names
cannot use this fallback to conceal an invalid row.

On insert/update, set `last_import_id` to the successful job; set `updated_at` on
updates and retain `created_at`. On unchanged rows, retain all employee metadata,
including `last_import_id` and timestamps; the new row-result record proves the
employee was seen again. Never modify any order/customer/item snapshots, order
identity, receipt history, or financial records during an employee import.

A deliberate re-import creates a new job/history, matching the same employee
identities. An identical file normally produces unchanged results; a previously
imported older file can still change current directory values, so do not silently
schedule or replay it. The source hash is traceability metadata, not a uniqueness
ban or proof of freshness. Version 1 has no inferred export-date precedence rule.

## 4. Whole-file transaction and rollback

**Adopted Version 1 policy:** Reject the whole batch if any record is invalid;
do not partially insert/update employees. This replaces the database proposal's
earlier proposed partial-acceptance default. No partial-acceptance mode is enabled.

1. Require an explicitly authorized actor supplied by a future verified server
   session. Persist a `processing` import job with that actor, start time, SHA-256
   of the uploaded bytes, encoding and delimiter. Do not store the raw file or
   client-provided actor identity in history.
2. Parse and validate the entire file before employee writes. If valid, begin one
   apply transaction, recheck authorization and compare against current employees.
   Serialize import apply operations; lock matched employees in consistent identity
   order. Coordinate with the existing order service's shared employee locks so
   new order snapshots see a consistent committed directory state.
3. Commit employee changes, successful row results, exact counts, completion time,
   `completed` status and audit events together. Check counts against row outcomes.
   Audit the job and inserted/changed employees with verified actor/time, target,
   action and necessary mapped before/after values. Unchanged employees need only
   row results, not fabricated employee-change events.
4. On validation failure, write no employees. On apply/database/audit failure,
   roll back **all** employee writes, success results and success audits. In a
   separate transaction, record the failed job, completion time, safe diagnostics
   and failure audit. Never report a failed batch as partially successful.
   If failure-history persistence also fails, report failure explicitly; do not
   claim that a durable job result exists. Recovery of interrupted `processing`
   jobs must be defined before live use.

Only an enabled Admin, rechecked from the stored user through a trusted actor
context, may execute the service. Authentication and protected import endpoints
remain unimplemented; role-view permissions are not inferred from import execution.

## 5. History and administrator-facing summaries

Use the existing `employee_imports`, `employee_import_rows` and `audit_events`;
no additional tables or outcome enums are needed for the specified behavior.

- Job summary: ID, authorized actor, timestamps, source hash, encoding/delimiter,
  status, total/inserted/updated/unchanged/rejected counts and safe file error code.
  Successful totals equal the sum of outcome counts; rejected count is zero.
- Successful row results: one per data record, `inserted`, `updated` or `unchanged`,
  referencing its employee. `row_number` is the 1-based data-record index excluding
  the header; quoted multiline records count once, not as several physical lines.
- Fully parsed but invalid batch: mark **all** data records `rejected`, with
  inserted/updated/unchanged counts zero and rejected count equal to total rows.
  Invalid records carry their field/error codes; otherwise valid records carry
  `BATCH_NOT_APPLIED`. Distinguish error-bearing records from records blocked by
  batch rollback in the summary. Do not label unapplied rows inserted/updated.
- Fatal encoding/header/CSV parsing failures: use `failed` plus a file error code;
  if a reliable complete record count cannot be established, store zero counts
  and no row results. Explain “row count unavailable,” not “zero employees found.”
  Apply failures after a complete parse reject all records with
  `BATCH_NOT_APPLIED`; summarize the safe job-level failure separately.
- For rejected rows, keep the nullable employee FK NULL; do not create employees
  merely to record errors. Store only data-record index and allowlisted field/error
  codes in `issues`, never raw values, contact data, SQL exceptions or CSV lines.
  Examples: `REQUIRED`, `DUPLICATE_EMPLOYEE_NUMBER`, `ROW_WIDTH`, `INVALID_TEXT`;
  file codes: `INVALID_ENCODING`, `INVALID_HEADERS`, `INVALID_CSV`, `APPLY_FAILED`.
- Administrator summaries show counts and actionable row/field messages, e.g.
  **“Record 2: full_name is required. No employee changes were applied.”**
  Restricted employee-change audits may retain necessary approved before/after
  values; routine logs/error summaries must not reproduce them. File storage,
  history access and retention remain subject to approved local privacy controls.

## 6. Synthetic acceptance cases

Acceptance cases for the service and disposable PostgreSQL tests.
Use fictional identifiers such as `SYN-0001` and names such as `Synthetic Person A`.
Generate all ten columns with empty ignored cells; never copy real export rows.

| Case | Expected result |
| --- | --- |
| Valid new `SYN-0001`; optional fields blank | One inserted employee, optional NULLs, completed job and matching row/audit history. |
| Existing `SYN-0001`; changed name/position/campaign/line of business | Update only effective changed fields; preserve identity and every existing order snapshot. |
| Identical re-import or changes only to ignored columns | New completed job, unchanged result; no duplicate identity or employee timestamp/link update. |
| Existing nonblank campaign; incoming blank/whitespace | Retain campaign; unchanged unless another effective field differs. |
| Employee omitted from next export | Employee and historical orders remain; no new eligibility state. |
| Missing number or blank required name alongside a valid row | Failed batch; both rejected, valid row marked `BATCH_NOT_APPLIED`; no employee changes. |
| Duplicate `SYN-0001`, with equal or conflicting values | Report every duplicate occurrence; fail whole batch without choosing a winner. |
| Synthetic text IDs `0001` and `1`; equal names on distinct IDs | Preserve distinct identities; reject an identifier with surrounding whitespace rather than silently merging it. |
| Valid UTF-8 with/without BOM; quoted comma or Unicode name | Parse correctly, preserve approved text, match exact header names. |
| Bad encoding, duplicate/missing/extra headers, bad quoting, wrong row width, NUL mapped text or empty export | Fail safely with the appropriate file/record code and zero employee writes. |
| Failure during employee writes, row-result/audit insertion or final commit | Roll back the entire apply transaction; separately persist a truthful failed-job summary. |
| Concurrent imports and order creation | Imports serialize/recompare current data; order snapshots contain one consistent committed employee revision. |
| Re-import an older valid file | No duplicate identities; explicit current-field comparison applies, with no invented timestamp precedence. |
| Unauthorized caller, forged actor or missing secure session provider | Deny execution/exposure; no default identity or unapproved role permission. |

## 7. Remaining decisions before live exposure

- **Execution permission is settled:** Admin only. Decide which roles may view
  job/row results separately; deny undefined access. Protected HTTP exposure
  requires real authentication, which is currently absent.
- **Before live use:** Agree export freshness/refresh responsibility, handling of
  interrupted jobs, upload limits, and local file/history retention and access.
  These do not authorize extra employee columns, status filters, automatic
  deletion, contact storage or additional import modes.

Keep authenticated HTTP integration separate until its security boundary and the
remaining operational controls are implemented and tested.
