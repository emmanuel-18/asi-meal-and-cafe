# ASI Meal Management System — Engineering Instructions

## Project Scope
- This is an independent internal application for ASI Meal employee purchases, sales, payments, summaries, and salary-deduction reporting.
- Version 1 excludes inventory and stock management.
- HRMS remains the source of truth for employee information. Employee data is imported through a validated CSV export.
- Do not add features outside the agreed scope without discussing them first.

## Architecture
- Use a modular monolith with a FastAPI backend, Next.js App Router frontend, and PostgreSQL database.
- Keep business rules and use cases separate from HTTP handlers, UI components, and persistence details.
- Introduce modules and abstractions when required by a real use case. Avoid speculative layers and empty abstractions.
- Use explicit database transactions and database constraints for operations that must remain consistent.
- Review relevant project documentation and decisions before making changes.

## Security and Privacy
- Keep core application data and processing within the approved local/on-premises environment.
- Never commit credentials, secrets, private keys, production employee data, or sensitive logs.
- Validate input at every system boundary, including CSV imports, HTTP requests, and database operations.
- Enforce authorization on the backend for every protected operation. Frontend visibility is not authorization.
- Deny access by default. Do not create default accounts, shared credentials, hardcoded passwords, or pretend authentication is implemented.
- Do not enable production use until authentication, authorization, configuration, and deployment safeguards are implemented and tested.

## Sales, Payments, and Financial Records
- Do not invent business policies for prices, payment confirmation, corrections, cancellations, salary deductions, or reporting periods.
- Record consequential changes with the verified actor, timestamp, reason, and before/after values.
- Preserve traceability between sales, payments, and salary-deduction reports.
- Prevent duplicate processing and inconsistent financial updates through appropriate constraints and transactions.
- Confirm business rules with the responsible stakeholders before implementing them.

## Employee Imports
- Validate CSV structure, required fields, encoding, duplicate employee identifiers, and malformed records.
- Track import results and report rejected records clearly without exposing unnecessary personal information.
- Do not silently overwrite employee information or assume every exported field should be editable in this application.
- Use synthetic or approved redacted data for tests and development.

## Database and Operations
- Use SQLAlchemy and Alembic for database access and schema migrations.
- Review generated migrations and test upgrades against a disposable database.
- Do not run destructive migrations or delete database volumes without explicit authorization.
- Plan backups and verify restoration before production use.
- Never claim production readiness without verifying the relevant deployment and recovery controls.

## Testing and Verification
- Add relevant automated tests for business rules, authorization, imports, transaction integrity, and reporting.
- Run applicable tests, type checks, lint, and build checks after changes.
- Report exactly what ran, passed, failed, or was skipped.
- Distinguish automated test results from behavior verified in the running application.
- Keep changes focused and preserve unrelated work.

## Frontend
- Build a responsive interface for desktop, tablet, and mobile.
- Prefer clear, accessible, consistent interfaces over unnecessary animation.
- Brand palette: navy #160D76, blue #4094D9, orange #F08530, off-white #FFFFFA, and dark #222222.
- Preferred typography: Cardo for headings and Open Sans for body text.
- After frontend changes for the local demo, rebuild and reload the identified local frontend and verify it responds, unless the current task explicitly prohibits a restart or the environment cannot be identified safely. Preserve the database and unrelated services.

## Working Method
- Work incrementally and explain the purpose of each step.
- Inspect before editing. Avoid overwriting existing files without checking them.
- Ask for clarification when a business decision affects financial correctness, access control, or employee privacy.
- Do not introduce AI features or cloud dependencies into the core application unless explicitly approved.
