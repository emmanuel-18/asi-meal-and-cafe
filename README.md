# ASI Meal Management System

An internal application for managing ASI Meal employee purchases, sales,
payment tracking, sales summaries, and salary-deduction reporting.

## Project Status

**Stage:** Initial project foundation

The repository structure and engineering instructions are being established.
Business features, database schemas, authentication, and production deployment
have not yet been implemented.

## Version 1 Scope

### Included
- Employee directory imported from the HRMS CSV exporter.
- Employee search and directory management within approved permissions.
- Meal purchase and sales recording.
- Payment tracking for approved payment methods.
- Sales summaries and reconciliation support.
- Salary-deduction report generation.
- User access control and financial audit history.
- Import history and validation feedback.

### Excluded
- Inventory and stock management.
- Direct HRMS API integration.
- Automated order notifications.
- AI-based transaction approval.
- Cloud-dependent core processing.

## Technology Stack

The initial technical direction is:

- Frontend: Next.js App Router, React, and TypeScript.
- UI: Tailwind CSS and shadcn/ui.
- Backend: Python, FastAPI, and Pydantic.
- Persistence: SQLAlchemy and Alembic.
- Database: PostgreSQL.
- Deployment: Docker Compose for local/on-premises operation.
- Testing: pytest, Vitest/Testing Library, and Playwright.

Dependencies and versions will be selected and locked during foundation setup.

## Employee Data

HRMS remains the source of truth for employee information. The application
will consume validated CSV exports from the ASI Meal employee exporter.

Employee exports contain personal information and must be transferred, stored,
and processed only through approved, access-controlled locations.

Do not commit real employee exports, production records, credentials, or secrets.

## Business Rules

Prices, payment confirmation, correction procedures, salary-deduction rules,
reporting periods, and other financial policies must be confirmed with the
responsible stakeholders before implementation.

Financial reports must be traceable to the underlying transaction records.

## Development Principles

- Keep business logic separate from HTTP handlers and UI components.
- Validate inputs and enforce authorization on the backend.
- Use explicit database transactions and constraints for financial consistency.
- Record consequential changes in an audit trail.
- Test with synthetic or approved redacted data.
- Plan and verify backups and restoration before production use.

See [AGENTS.md](AGENTS.md) for the repository's engineering instructions.

## Run locally with Docker Compose

Install Docker with Compose, then copy `infra/.env.example` to `infra/.env`
and set a PostgreSQL user, password, and database name. Keep this file private.
From the repository root, run:

```powershell
docker compose --env-file infra/.env -f infra/compose.yaml up --build -d
```

The frontend is available at http://localhost:3000 and the API health endpoint
at http://localhost:8000/health. PostgreSQL is accessible only to containers on
the Compose network; its data persists in a named Docker volume. The current API
does not yet connect to the database. To stop the services without removing the
database volume, run:

```powershell
docker compose --env-file infra/.env -f infra/compose.yaml down
```

The database credentials initialize a new volume; changing them later does not
update an existing database. This setup is for local development, not production.

## Development Status

No business features are implemented yet. Do not use this project for
production transactions until security controls, business rules, testing,
deployment, and recovery procedures have been reviewed and approved.
