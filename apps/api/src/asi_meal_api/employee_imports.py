"""Atomic HRMS CSV import; callers supply a trusted actor, never CSV identity.

No HTTP endpoint, authentication provider, file persistence or global connection.
Only mapped values survive parsing; diagnostics contain field/error codes only.
"""

from collections import Counter
from collections.abc import Callable
import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import io
from typing import BinaryIO

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from asi_meal_api.db import models as m
from asi_meal_api.orders import ActorContext, Forbidden


FIELDS = ("employee_number", "full_name", "position", "campaign", "line_of_business")
HEADERS = FIELDS + ("assigned_site", "email_address", "primary_contact_number",
                    "alternative_contact_number", "alternative_contact_number_2")
IMPORT_LOCK = int.from_bytes(b"ASIHRMS1", "big")


class ImportSourceError(ValueError):
    """No complete binary source was obtained; no import job could be recorded."""


class ImportHistoryError(RuntimeError):
    def __init__(self, import_id: int):
        super().__init__("Import result could not be confirmed; failure history could not be saved")
        self.import_id = import_id


@dataclass(frozen=True, slots=True)
class ImportResult:
    import_id: int
    status: str
    total_rows: int
    inserted_rows: int
    updated_rows: int
    unchanged_rows: int
    rejected_rows: int
    file_error_code: str | None


@dataclass(slots=True)
class _Row:
    number: int
    values: dict[str, str] = field(default_factory=dict)
    issues: list[dict[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class _Parsed:
    rows: list[_Row] = field(default_factory=list)
    error: str | None = None


def _parse(data: bytes) -> _Parsed:
    try:
        decoded = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        return _Parsed(error="INVALID_ENCODING")
    reader = csv.reader(io.StringIO(decoded, newline=""), delimiter=",", strict=True)
    result = _Parsed()
    try:
        headers = next(reader, None)
        if headers is None:
            return _Parsed(error="EMPTY_EXPORT")
        # Header normalization is deliberately only BOM removal, never aliases,
        # whitespace/case guessing, or positional mapping of rearranged headers.
        if len(headers) != len(HEADERS) or set(headers) != set(HEADERS):
            return _Parsed(error="INVALID_HEADERS")
        positions = {name: headers.index(name) for name in FIELDS}
        for number, cells in enumerate(reader, 1):
            row = _Row(number)
            result.rows.append(row)
            if len(cells) != len(HEADERS):
                row.issues.append({"field": "record", "code": "ROW_WIDTH"})
                continue
            row.values = {name: cells[index] for name, index in positions.items()}
            for name, value in row.values.items():
                if "\x00" in value:
                    row.issues.append({"field": name, "code": "INVALID_TEXT"})
                if name in {"employee_number", "full_name"} and not value.strip():
                    row.issues.append({"field": name, "code": "REQUIRED"})
                elif name == "employee_number" and value != value.strip():
                    row.issues.append({"field": name, "code": "SURROUNDING_WHITESPACE"})
            row.values = {name: value if name == "employee_number" else value.strip()
                          for name, value in row.values.items()}
    except csv.Error:
        # An incomplete parse has no trustworthy whole-file row count. Discard
        # the prefix rather than imply that it represents the uploaded file.
        return _Parsed(error="INVALID_CSV")
    if not result.rows:
        return _Parsed(error="EMPTY_EXPORT")
    identifiers = Counter(row.values.get("employee_number") for row in result.rows if row.values.get("employee_number"))
    for row in result.rows:
        if identifiers[row.values.get("employee_number")] > 1:
            row.issues.append({"field": "employee_number", "code": "DUPLICATE_EMPLOYEE_NUMBER"})
    if any(row.issues for row in result.rows):
        result.error = "VALIDATION_FAILED"
    return result


class EmployeeImportService:
    def __init__(self, session_factory: Callable[[], Session]):
        self._sessions = session_factory

    @staticmethod
    def _admin(session: Session, actor: ActorContext) -> m.User:
        if (type(actor) is not ActorContext or type(actor.user_id) is not int
                or not 0 < actor.user_id <= 9223372036854775807):
            raise Forbidden("A trusted Admin actor context is required")
        user = session.scalar(select(m.User).where(m.User.id == actor.user_id).with_for_update(read=True))
        if user is None or not user.is_enabled or user.role_code != "admin":
            raise Forbidden("Only an enabled Admin may import employees")
        return user

    @staticmethod
    def _audit(session: Session, actor_id: int, action: str, entity: str, key: str,
               before: dict | None, after: dict) -> None:
        session.add(m.AuditEvent(actor_user_id=actor_id, action=action,
                                entity_type=entity, entity_key=key, before_values=before,
                                after_values=after, reason="HRMS CSV import"))

    @staticmethod
    def _result(job: m.EmployeeImport) -> ImportResult:
        return ImportResult(job.id, job.status, job.total_rows, job.inserted_rows,
                            job.updated_rows, job.unchanged_rows, job.rejected_rows, job.file_error_code)

    def import_csv(self, actor: ActorContext, source: bytes | BinaryIO) -> ImportResult:
        """Import the supplied binary source from its current position, once.

        Each call creates a deliberate new job; hashes never suppress a retry.
        Failures return status=failed after durable diagnostics, or raise a safe
        ImportHistoryError if that separate failure write also fails.
        """
        with self._sessions() as session, session.begin():
            user = self._admin(session, actor)
            try:
                data = source if isinstance(source, bytes) else source.read()
            except Exception:
                raise ImportSourceError("Unable to read a complete binary CSV source") from None
            if not isinstance(data, bytes):
                raise ImportSourceError("CSV source must provide bytes")
            job = m.EmployeeImport(uploaded_by=user.id, source_sha256=hashlib.sha256(data).hexdigest(),
                                   encoding="utf-8-sig", delimiter=",")
            session.add(job)
            session.flush()
            import_id = job.id
        parsed = _parse(data)
        if parsed.error:
            return self._failed(import_id, parsed, parsed.error)
        try:
            return self._apply(actor, import_id, parsed)
        except Forbidden:
            return self._failed(import_id, parsed, "AUTHORIZATION_CHANGED")
        except Exception:
            # Never include DB/CSV exception text or values in returned diagnostics.
            # The transaction context has already rolled back all employee writes.
            return self._failed(import_id, parsed, "APPLY_FAILED")

    def _apply(self, actor: ActorContext, import_id: int, parsed: _Parsed) -> ImportResult:
        with self._sessions() as session, session.begin():
            user = self._admin(session, actor)
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": IMPORT_LOCK})
            job = session.scalar(select(m.EmployeeImport).where(m.EmployeeImport.id == import_id).with_for_update())
            numbers = [row.values["employee_number"] for row in parsed.rows]
            employees = {employee.employee_number: employee for employee in session.scalars(
                select(m.Employee).where(m.Employee.employee_number.in_(numbers))
                .order_by(m.Employee.employee_number).with_for_update())}
            outcomes = []
            counts: Counter[str] = Counter()
            for row in parsed.rows:
                number = row.values["employee_number"]
                employee = employees.get(number)
                incoming = {key: value or None for key, value in row.values.items() if key != "employee_number"}
                if employee is None:
                    employee = m.Employee(employee_number=number, last_import_id=import_id, **incoming)
                    session.add(employee)
                    outcome = "inserted"
                    self._audit(session, user.id, "employee_import_inserted", "employees", number,
                                None, {"import_id": import_id, "fields": incoming})
                else:
                    # Blank optional input preserves the actual existing value.
                    effective = {key: (getattr(employee, key) if value is None else value)
                                 for key, value in incoming.items()}
                    changed = {key: value for key, value in effective.items()
                               if (getattr(employee, key).strip() if isinstance(getattr(employee, key), str)
                                   else getattr(employee, key)) != (value.strip() if isinstance(value, str) else value)}
                    outcome = "updated" if changed else "unchanged"
                    if changed:
                        before = {key: getattr(employee, key) for key in changed}
                        for key, value in changed.items():
                            setattr(employee, key, value)
                        employee.last_import_id = import_id
                        employee.updated_at = datetime.now(timezone.utc)
                        self._audit(session, user.id, "employee_import_updated", "employees", number,
                                    {"fields": before}, {"import_id": import_id, "fields": changed})
                counts[outcome] += 1
                outcomes.append(m.EmployeeImportRow(import_id=import_id, row_number=row.number,
                                                    employee_number=number, outcome=outcome))
            # Ensure newly inserted employee FKs exist before row-result insertion.
            session.flush()
            session.add_all(outcomes)
            job.total_rows = len(parsed.rows)
            job.inserted_rows = counts["inserted"]
            job.updated_rows = counts["updated"]
            job.unchanged_rows = counts["unchanged"]
            job.rejected_rows = 0
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            self._audit(session, user.id, "employee_import_completed", "employee_imports", str(import_id),
                        {"status": "processing"}, {"status": "completed", "total_rows": job.total_rows,
                        "inserted_rows": job.inserted_rows, "updated_rows": job.updated_rows,
                        "unchanged_rows": job.unchanged_rows, "rejected_rows": 0})
            session.flush()
            return self._result(job)

    def _failed(self, import_id: int, parsed: _Parsed, code: str) -> ImportResult:
        try:
            with self._sessions() as session, session.begin():
                job = session.scalar(select(m.EmployeeImport).where(m.EmployeeImport.id == import_id).with_for_update())
                # A commit acknowledgement/connection-close failure can occur
                # after a successful atomic commit. Never overwrite its durable
                # completed result or fabricate a failed batch in that case.
                if job.status != "processing":
                    return self._result(job)
                job.status = "failed"
                job.completed_at = datetime.now(timezone.utc)
                job.file_error_code = code
                job.total_rows = job.rejected_rows = len(parsed.rows)
                job.inserted_rows = job.updated_rows = job.unchanged_rows = 0
                for row in parsed.rows:
                    session.add(m.EmployeeImportRow(import_id=import_id, row_number=row.number,
                        employee_number=None, outcome="rejected",
                        issues=row.issues or [{"field": "record", "code": "BATCH_NOT_APPLIED"}]))
                # Attribution uses the original verified uploader, even if the
                # account was disabled during parsing. This records failure only.
                self._audit(session, job.uploaded_by, "employee_import_failed", "employee_imports", str(import_id),
                            {"status": "processing"}, {"status": "failed", "file_error_code": code,
                            "total_rows": job.total_rows, "rejected_rows": job.rejected_rows})
                session.flush()
                return self._result(job)
        except Exception:
            raise ImportHistoryError(import_id) from None
