"""Synthetic CSV and disposable PostgreSQL only; never read the HRMS export."""

from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import io
import threading
import time
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from asi_meal_api.employee_imports import (
    EmployeeImportService, HEADERS, ImportHistoryError, ImportSourceError,
)
from asi_meal_api.orders import ActorContext, Forbidden
from test_database import graph, sql
from test_orders import concurrent_env, request, state


def csv_bytes(rows, *, headers=HEADERS, bom=False):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        if isinstance(row, dict):
            writer.writerow([row.get(name, "") for name in headers])
        else:
            writer.writerow(row)
    return output.getvalue().encode("utf-8-sig" if bom else "utf-8")


def person(number="SYN-0001", name="Synthetic Person A", **kwargs):
    return dict(employee_number=number, full_name=name, **kwargs)


@pytest.fixture
def env(db):
    g = graph(db)
    assistant = sql(db, "INSERT INTO users (login_name,display_name,password_hash,role_code) "
                    "SELECT :login,'Synthetic Assistant',password_hash,'assistant_admin' FROM users "
                    "WHERE id=:id RETURNING id", login=uuid4().hex, id=g["actor"]).scalar_one()
    factory = sessionmaker(bind=db, join_transaction_mode="create_savepoint")
    return g, EmployeeImportService(factory), ActorContext(g["actor"]), ActorContext(assistant), factory


def employees(db):
    return [dict(row) for row in sql(db, "SELECT * FROM employees ORDER BY employee_number").mappings()]


def history(db, import_id):
    job = dict(sql(db, "SELECT * FROM employee_imports WHERE id=:id", id=import_id).mappings().one())
    rows = [dict(row) for row in sql(db, "SELECT * FROM employee_import_rows WHERE import_id=:id ORDER BY row_number",
                                   id=import_id).mappings()]
    audits = [dict(row) for row in sql(db, "SELECT * FROM audit_events WHERE entity_type='employee_imports' AND entity_key=:key ORDER BY id",
                                     key=str(import_id)).mappings()]
    return job, rows, audits


def test_insert_metadata_ignored_fields_and_reimport(db, env):
    g, service, admin, _, _ = env
    payload = csv_bytes([person(position="Synthetic Position", campaign="Synthetic Campaign",
        line_of_business="Synthetic LOB", assigned_site="PRIVATE_IGNORED_SITE",
        email_address="PRIVATE_IGNORED_EMAIL", primary_contact_number="PRIVATE_IGNORED_PHONE")])
    result = service.import_csv(admin, io.BytesIO(payload))
    assert result.status == "completed" and result.inserted_rows == result.total_rows == 1
    employee = next(e for e in employees(db) if e["employee_number"] == "SYN-0001")
    assert [employee[f] for f in ("full_name", "position", "campaign", "line_of_business")] == [
        "Synthetic Person A", "Synthetic Position", "Synthetic Campaign", "Synthetic LOB"]
    job, rows, audits = history(db, result.import_id)
    assert job["uploaded_by"] == admin.user_id and job["status"] == "completed"
    assert job["source_sha256"] == hashlib.sha256(payload).hexdigest()
    assert job["completed_at"] >= job["started_at"] and job["encoding"] == "utf-8-sig" and job["delimiter"] == ","
    assert len(rows) == 1 and rows[0]["outcome"] == "inserted" and rows[0]["employee_number"] == "SYN-0001"
    assert len(audits) == 1 and audits[0]["action"] == "employee_import_completed"
    assert audits[0]["actor_user_id"] == admin.user_id
    all_audits = [dict(row) for row in sql(db, "SELECT * FROM audit_events").mappings()]
    assert len(all_audits) == 2
    assert "PRIVATE_IGNORED" not in repr((employees(db), job, rows, all_audits))
    again = service.import_csv(admin, payload)
    assert again.import_id != result.import_id and again.unchanged_rows == 1 and again.inserted_rows == 0
    assert next(e for e in employees(db) if e["employee_number"] == "SYN-0001") == employee
    assert history(db, again.import_id)[1][0]["outcome"] == "unchanged"
    assert sql(db, "SELECT count(*) FROM audit_events WHERE entity_type='employees'").scalar_one() == 1
    ignored_change = service.import_csv(admin, csv_bytes([person(position="Synthetic Position", campaign="Synthetic Campaign",
        line_of_business="Synthetic LOB", email_address="PRIVATE_IGNORED_CHANGED")]))
    assert ignored_change.unchanged_rows == 1
    assert next(e for e in employees(db) if e["employee_number"] == "SYN-0001") == employee
    assert any(e["employee_number"] == g["employee"] for e in employees(db))


def test_updates_blank_optional_preservation_absent_employees_and_snapshots(db, env):
    g, service, admin, _, factory = env
    from asi_meal_api.orders import OrderService
    order = OrderService(factory).create_pending(admin, request(g))
    original_order = state(db, order.order_id)
    first = service.import_csv(admin, csv_bytes([person(g["employee"], "Synthetic Employee",
        position="Synthetic Position", campaign="Synthetic Campaign", line_of_business="Synthetic LOB"), person()]))
    before = {e["employee_number"]: e for e in employees(db)}
    result = service.import_csv(admin, csv_bytes([person(g["employee"], "  Synthetic Updated Name  ",
        position="   ", campaign="Synthetic Updated Campaign", line_of_business="")]))
    assert result.updated_rows == 1 and result.inserted_rows == result.unchanged_rows == 0
    after = {e["employee_number"]: e for e in employees(db)}
    updated = after[g["employee"]]
    assert updated["full_name"] == "Synthetic Updated Name" and updated["campaign"] == "Synthetic Updated Campaign"
    assert updated["position"] == "Synthetic Position" and updated["line_of_business"] == "Synthetic LOB"
    assert updated["created_at"] == before[g["employee"]]["created_at"]
    assert updated["last_import_id"] == result.import_id != first.import_id
    assert after["SYN-0001"] == before["SYN-0001"]
    assert state(db, order.order_id) == original_order
    audit = sql(db, "SELECT before_values,after_values FROM audit_events WHERE action='employee_import_updated' "
                "AND after_values->>'import_id'=:id", id=str(result.import_id)).mappings().one()
    assert audit["before_values"]["fields"] == {"full_name": "Synthetic Employee", "campaign": "Synthetic Campaign"}
    assert audit["after_values"]["fields"] == {"full_name": "Synthetic Updated Name", "campaign": "Synthetic Updated Campaign"}
    same = service.import_csv(admin, csv_bytes([person(g["employee"], "Synthetic Updated Name")]))
    assert same.unchanged_rows == 1 and employees(db) == list(after.values())


def test_text_identity_bom_reordered_headers_and_quoted_unicode(db, env):
    _, service, admin, _, _ = env
    result = service.import_csv(admin, csv_bytes([person("0001", 'Synthetic, "Name"\nUnicode \u00e9'),
                                                 person("1", "Synthetic Person A"), person("ABC"), person("abc")],
                                                 headers=tuple(reversed(HEADERS)), bom=True))
    assert result.inserted_rows == 4
    selected = {e["employee_number"]: e for e in employees(db)}
    assert {"0001", "1", "ABC", "abc"} <= selected.keys()
    assert selected["0001"]["full_name"] == 'Synthetic, "Name"\nUnicode \u00e9'
    assert selected["1"]["position"] is None
    assert [r["row_number"] for r in history(db, result.import_id)[1]] == [1, 2, 3, 4]


@pytest.mark.parametrize("payload,code", [
    (b"\xff\xfe", "INVALID_ENCODING"), (b"", "EMPTY_EXPORT"),
    (csv_bytes([]), "EMPTY_EXPORT"),
    (csv_bytes([person()], headers=HEADERS[:-1]), "INVALID_HEADERS"),
    (csv_bytes([person()], headers=tuple(name for name in HEADERS if name != "full_name")), "INVALID_HEADERS"),
    (csv_bytes([person()], headers=HEADERS + ("unknown",)), "INVALID_HEADERS"),
    (csv_bytes([person()], headers=(HEADERS[0],) + HEADERS[:-1]), "INVALID_HEADERS"),
    (csv_bytes([person()], headers=(" Employee_Number ",) + HEADERS[1:]), "INVALID_HEADERS"),
    (csv_bytes([]) + b'"unterminated', "INVALID_CSV"),
    (csv_bytes([person()]) + b'"unterminated', "INVALID_CSV"),
])
def test_fatal_file_errors_leave_no_employee_changes(db, env, payload, code):
    _, service, admin, _, _ = env
    before = employees(db)
    result = service.import_csv(admin, payload)
    assert result.status == "failed" and result.file_error_code == code
    assert result.total_rows == result.rejected_rows == result.inserted_rows == result.updated_rows == result.unchanged_rows == 0
    assert employees(db) == before
    job, rows, audits = history(db, result.import_id)
    assert job["completed_at"] and rows == [] and len(audits) == 1
    assert audits[0]["action"] == "employee_import_failed" and audits[0]["actor_user_id"] == admin.user_id


@pytest.mark.parametrize("bad,field,code", [
    (person(number=""), "employee_number", "REQUIRED"),
    (person(number=" \t"), "employee_number", "REQUIRED"),
    (person(number=" SYN-0001"), "employee_number", "SURROUNDING_WHITESPACE"),
    (person(name=" \n"), "full_name", "REQUIRED"),
    (person(name="PRIVATE_BAD\x00NAME"), "full_name", "INVALID_TEXT"),
    (person(position="PRIVATE_BAD\x00POSITION"), "position", "INVALID_TEXT"),
    (["PRIVATE_BAD_ROW"], "record", "ROW_WIDTH"), ([], "record", "ROW_WIDTH"),
])
def test_invalid_row_rejects_whole_file_with_safe_diagnostics(db, env, bad, field, code):
    g, service, admin, _, _ = env
    before = employees(db)
    result = service.import_csv(admin, csv_bytes([person(g["employee"], "Synthetic Would Change"), bad]))
    assert result.status == "failed" and result.total_rows == result.rejected_rows == 2
    assert result.inserted_rows == result.updated_rows == result.unchanged_rows == 0
    assert employees(db) == before
    job, rows, audits = history(db, result.import_id)
    assert all(r["outcome"] == "rejected" and r["employee_number"] is None for r in rows)
    assert rows[0]["issues"] == [{"field": "record", "code": "BATCH_NOT_APPLIED"}]
    assert {"field": field, "code": code} in rows[1]["issues"]
    assert "PRIVATE_BAD" not in repr((result, job, rows, audits))
    assert sql(db, "SELECT count(*) FROM audit_events WHERE entity_type='employees'").scalar_one() == 0


@pytest.mark.parametrize("conflicting", [False, True])
def test_every_duplicate_occurrence_rejected(db, env, conflicting):
    _, service, admin, _, _ = env
    before = employees(db)
    result = service.import_csv(admin, csv_bytes([person(), person(name="Synthetic Different" if conflicting else "Synthetic Person A"),
                                                 person("SYN-0002")]))
    assert result.total_rows == result.rejected_rows == 3 and result.status == "failed"
    rows = history(db, result.import_id)[1]
    assert all({"field": "employee_number", "code": "DUPLICATE_EMPLOYEE_NUMBER"} in r["issues"] for r in rows[:2])
    assert rows[2]["issues"] == [{"field": "record", "code": "BATCH_NOT_APPLIED"}]
    assert employees(db) == before


def test_admin_only_and_binary_source_boundary(db, env):
    _, service, admin, assistant, _ = env
    payload = csv_bytes([person()])
    original_jobs = sql(db, "SELECT count(*) FROM employee_imports").scalar_one()
    sql(db, "UPDATE users SET is_enabled=false WHERE id=:id", id=admin.user_id)
    for actor in (admin, assistant, ActorContext(99999999), ActorContext(True),
                  {"user_id": admin.user_id, "role": "admin"}, None):
        with pytest.raises(Forbidden):
            service.import_csv(actor, payload)
    assert sql(db, "SELECT count(*) FROM employee_imports").scalar_one() == original_jobs
    sql(db, "UPDATE users SET is_enabled=true WHERE id=:id", id=admin.user_id)
    for source in (io.StringIO("synthetic text"), None):
        with pytest.raises(ImportSourceError):
            service.import_csv(admin, source)
    assert sql(db, "SELECT count(*) FROM employee_imports").scalar_one() == original_jobs


def test_admin_disabled_during_validation_leaves_failed_attempt(db, env, monkeypatch):
    _, service, admin, _, _ = env
    from asi_meal_api import employee_imports
    original_parse = employee_imports._parse

    def revoke_after_parse(data):
        parsed = original_parse(data)
        sql(db, "UPDATE users SET is_enabled=false WHERE id=:id", id=admin.user_id)
        return parsed

    monkeypatch.setattr(employee_imports, "_parse", revoke_after_parse)
    before = employees(db)
    result = service.import_csv(admin, csv_bytes([person()]))
    assert result.status == "failed" and result.file_error_code == "AUTHORIZATION_CHANGED"
    assert result.rejected_rows == 1 and employees(db) == before
    assert history(db, result.import_id)[2][0]["actor_user_id"] == admin.user_id


@pytest.mark.parametrize("table", ["employees", "employee_import_rows", "audit_events", "commit"])
def test_apply_failure_rolls_back_changes_and_records_failed_job(db, env, table):
    g, service, admin, _, factory = env
    before = employees(db)
    failed = []

    def fail(conn, cursor, statement, parameters, context, executemany):
        target = (statement.startswith("UPDATE employees ") if table == "employees"
                  else statement.startswith(f"INSERT INTO {table} "))
        if target and not failed:
            failed.append(True)
        else:
            target = False
        if target:
            cursor.execute("SELECT 1/0")

    def fail_commit(session):
        failed.append(True)
        # First commit creates the job; second commits the employee apply batch.
        if len(failed) == 2:
            raise RuntimeError("Synthetic failure at apply commit")

    if table == "commit":
        event.listen(factory, "before_commit", fail_commit)
    else:
        event.listen(db, "before_cursor_execute", fail)
    try:
        result = service.import_csv(admin, csv_bytes([person(g["employee"], "Synthetic Would Change"), person()]))
    finally:
        if table == "commit":
            event.remove(factory, "before_commit", fail_commit)
        else:
            event.remove(db, "before_cursor_execute", fail)
    assert failed and result.status == "failed" and result.file_error_code == "APPLY_FAILED"
    assert employees(db) == before
    job, rows, audits = history(db, result.import_id)
    assert job["inserted_rows"] == job["updated_rows"] == job["unchanged_rows"] == 0
    assert job["total_rows"] == job["rejected_rows"] == 2 and len(rows) == 2
    assert len(audits) == 1 and audits[0]["action"] == "employee_import_failed"
    assert sql(db, "SELECT count(*) FROM audit_events WHERE entity_type='employees'").scalar_one() == 0


def test_completed_job_not_overwritten_after_commit_ack_failure(db, env, monkeypatch):
    _, service, admin, _, _ = env
    original_apply = service._apply

    def failed_ack(*args):
        original_apply(*args)
        raise RuntimeError("Synthetic failure after commit")

    monkeypatch.setattr(service, "_apply", failed_ack)
    result = service.import_csv(admin, csv_bytes([person()]))
    assert result.status == "completed" and result.inserted_rows == 1
    assert history(db, result.import_id)[2][0]["action"] == "employee_import_completed"


def test_failure_history_failure_is_reported_truthfully(db, env, monkeypatch):
    _, service, admin, _, _ = env

    def fail(*args, **kwargs):
        raise RuntimeError("PRIVATE_EXCEPTION_DETAILS")

    monkeypatch.setattr(service, "_audit", fail)
    before = employees(db)
    with pytest.raises(ImportHistoryError) as raised:
        service.import_csv(admin, csv_bytes([person()]))
    assert "PRIVATE_EXCEPTION" not in str(raised.value) and employees(db) == before
    job, rows, audits = history(db, raised.value.import_id)
    assert job["status"] == "processing" and not rows and not audits


def test_concurrent_imports_serialize_and_recompare(concurrent_env):
    engine, _, _, admin = concurrent_env
    service = EmployeeImportService(sessionmaker(bind=engine))
    first_locked = threading.Event()
    attempting = threading.Event()
    release = threading.Event()
    second_pid = []

    def before(conn, cursor, statement, parameters, context, executemany):
        if "pg_advisory_xact_lock" in statement and threading.current_thread().name.startswith("second"):
            second_pid.append(conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one())
            attempting.set()

    def after(conn, cursor, statement, parameters, context, executemany):
        if "pg_advisory_xact_lock" in statement and threading.current_thread().name.startswith("first"):
            first_locked.set()
            assert release.wait(10)

    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="first") as p1, ThreadPoolExecutor(max_workers=1, thread_name_prefix="second") as p2:
            payload = csv_bytes([person()])
            f1 = p1.submit(service.import_csv, admin, payload)
            assert first_locked.wait(10)
            f2 = p2.submit(service.import_csv, admin, payload)
            assert attempting.wait(10)
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if sql(observer, "SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid", pid=second_pid[0]).scalar_one() == "Lock":
                        break
                    time.sleep(0.01)
                else:
                    pytest.fail("Concurrent import did not wait on serialization lock")
            assert not f2.done()
            release.set()
            r1, r2 = f1.result(timeout=15), f2.result(timeout=15)
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)
    assert r1.inserted_rows == 1 and r2.unchanged_rows == 1
    with engine.begin() as c:
        assert sql(c, "SELECT count(*) FROM employees WHERE employee_number='SYN-0001'").scalar_one() == 1
        assert history(c, r1.import_id)[1][0]["outcome"] == "inserted"
        assert history(c, r2.import_id)[1][0]["outcome"] == "unchanged"
