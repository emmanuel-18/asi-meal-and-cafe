"""Service integration tests: synthetic actors are fixtures, never authentication."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from decimal import Decimal
import threading
import time
from uuid import uuid4

from alembic import command
import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker

from asi_meal_api.orders import (
    ActorContext, Allocation, Conflict, Correction, CORRECTION_REASONS, CreateOrder,
    EditPending, Forbidden, ItemSelection, NotFound, OrderError, OrderService, QuantityChange,
)
from conftest import alembic_config
from test_database import flush_constraints, graph, sql


@pytest.fixture
def env(db):
    g = graph(db)
    assistant = sql(db, "INSERT INTO users (login_name,display_name,password_hash,role_code) "
                    "SELECT :login,'Synthetic Assistant',password_hash,'assistant_admin' "
                    "FROM users WHERE id=:id RETURNING id", login=uuid4().hex, id=g["actor"]).scalar_one()
    service = OrderService(sessionmaker(bind=db, join_transaction_mode="create_savepoint"))
    return g, service, ActorContext(g["actor"]), ActorContext(assistant)


def request(g, **kwargs):
    result = CreateOrder(uuid4(), g["day"], g["menu"],
                         tuple(ItemSelection(i, q) for i, q in zip(g["offerings"], (1, 2, 3))),
                         (Allocation("gcash", Decimal("200")), Allocation("cash", Decimal("45"))),
                         employee_number=g["employee"])
    return replace(result, **kwargs)


def state(db, order_id):
    flush_constraints(db)
    order = sql(db, "SELECT id,version,is_received,menu_id,service_date,employee_number,visitor_id,"
                "customer_name_snapshot,receipt_changed_by,receipt_changed_at FROM orders WHERE id=:id", id=order_id).mappings().one()
    lines = sql(db, "SELECT id,source_menu_item_id,item_name,category_code_snapshot,unit_price,quantity,line_total "
                "FROM order_items WHERE order_id=:id ORDER BY line_number", id=order_id).mappings().all()
    allocations = sql(db, "SELECT id,payment_category_code,amount,created_by,updated_by FROM payment_allocations "
                      "WHERE order_id=:id ORDER BY payment_category_code", id=order_id).mappings().all()
    audits = sql(db, "SELECT * FROM audit_events WHERE entity_type='orders' AND entity_key=:key ORDER BY id",
                 key=str(order_id)).mappings().all()
    receipts = sql(db, "SELECT * FROM receipt_events WHERE order_id=:id ORDER BY audit_event_id", id=order_id).mappings().all()
    return dict(order=dict(order), lines=[dict(i) for i in lines], allocations=[dict(a) for a in allocations],
                audits=[dict(a) for a in audits], receipts=[dict(r) for r in receipts])


def counts(db):
    return tuple(sql(db, f"SELECT count(*) FROM {table}").scalar_one() for table in
                 ("orders", "order_items", "payment_allocations", "audit_events", "receipt_events"))


@pytest.mark.parametrize("visitor", [False, True])
def test_create_snapshots_and_consolidated_allocations(db, env, visitor):
    g, service, admin, assistant = env
    args = dict(employee_number=None, visitor_id=g["visitor"],
                allocations=(Allocation("finance", Decimal("200")), Allocation("finance", Decimal("45")))) if visitor else {}
    result = service.create_pending(assistant, request(g, **args))
    saved = state(db, result.order_id)
    assert not saved["order"]["is_received"] and saved["order"]["version"] == 1
    assert result.total == Decimal("245.00")
    assert saved["order"]["menu_id"] == g["menu"]
    assert saved["order"]["customer_name_snapshot"] == ("Synthetic Visitor" if visitor else "Synthetic Employee")
    assert [line["unit_price"] for line in saved["lines"]] == list(map(Decimal, ("50", "75", "15")))
    assert [line["quantity"] for line in saved["lines"]] == [1, 2, 3]
    assert [line["source_menu_item_id"] for line in saved["lines"]] == g["offerings"]
    assert sum(a["amount"] for a in saved["allocations"]) == Decimal("245")
    assert len(saved["allocations"]) == (1 if visitor else 2)
    assert all(a["created_by"] == assistant.user_id == a["updated_by"] for a in saved["allocations"])
    assert len(saved["audits"]) == 1 and not saved["receipts"]
    assert saved["audits"][0]["actor_user_id"] == assistant.user_id
    assert saved["audits"][0]["after_values"]["request"]["service_date"] == g["day"].isoformat()
    assert counts(db) == (1, 3, 1 if visitor else 2, 1, 0)


@pytest.mark.parametrize("invalid", [
    {"employee_number": None}, {"visitor_id": 99999999}, {"employee_number": "missing"},
    {"employee_number": None, "visitor_id": 99999999},
    {"service_date": date(2040, 2, 1)}, {"menu_id": 99999999}, {"items": ()},
    {"items": (ItemSelection(99999999, 1),)}, {"items": (ItemSelection(1, 0),)},
    {"items": (ItemSelection(1, -1),)}, {"items": (ItemSelection(1, True),)},
    {"items": (ItemSelection(1, 1.5),)}, {"items": (ItemSelection(1, 2147483648),)},
    {"allocations": (Allocation("for_deposit", Decimal("245")),)},
    {"allocations": (Allocation("cash", Decimal("0")),)},
    {"allocations": (Allocation("cash", Decimal("-1")),)},
    {"allocations": (Allocation("cash", Decimal("NaN")),)},
    {"allocations": (Allocation("cash", Decimal("Infinity")),)},
    {"allocations": (Allocation("cash", Decimal("1.001")),)},
    {"allocations": (Allocation("cash", Decimal("10000000000")),)},
    {"allocations": (Allocation("cash", 1.0),)}, {"allocations": (Allocation("cash", "245"),)},
    {"request_key": "not-a-uuid"}, {"service_date": "2040-01-02"},
])
def test_invalid_creation_is_atomic(db, env, invalid):
    g, service, admin, _ = env
    with pytest.raises(OrderError):
        service.create_pending(admin, request(g, **invalid))
    flush_constraints(db)
    assert counts(db) == (0, 0, 0, 0, 0)


def test_wrong_menu_and_visitor_categories(db, env):
    g, service, admin, _ = env
    # Existing but unassigned menu, and an existing offering of another menu.
    with pytest.raises(OrderError):
        service.create_pending(admin, request(g, menu_id=g["other"]))
    source = sql(db, "INSERT INTO menu_items (menu_id,dish_id,item_name,category_code,unit_price) "
                 "VALUES (:menu,:dish,'Synthetic foreign item','vegetable',50) RETURNING id",
                 menu=g["other"], dish=g["dishes"][0]).scalar_one()
    with pytest.raises(OrderError):
        service.create_pending(admin, request(g, items=(ItemSelection(source, 1),)))
    with pytest.raises(OrderError):
        service.create_pending(admin, request(g, employee_number=None, visitor_id=g["visitor"]))
    assert counts(db) == (0, 0, 0, 0, 0)


def test_price_overflow_and_allocation_consolidation_overflow(db, env):
    g, service, admin, _ = env
    sql(db, "UPDATE menu_items SET unit_price=9999999999.99 WHERE id=:id", id=g["offerings"][0])
    with pytest.raises(OrderError):
        service.create_pending(admin, request(g, items=(ItemSelection(g["offerings"][0], 2),)))
    with pytest.raises(OrderError):
        service.create_pending(admin, request(g, allocations=(Allocation("cash", Decimal("9999999999.99")),
                                                              Allocation("cash", Decimal("0.01")))))
    assert counts(db) == (0, 0, 0, 0, 0)


def test_retry_uses_original_request_after_edit_and_menu_changes(db, env):
    g, service, admin, assistant = env
    original = request(g)
    created = service.create_pending(admin, original)
    assert service.create_pending(admin, original) == created
    first = state(db, created.order_id)
    edited = service.edit_pending(assistant, created.order_id, 1,
                                 EditPending(quantities=(QuantityChange(first["lines"][0]["id"], 2),)))
    sql(db, "UPDATE menu_items SET unit_price=51 WHERE id=:id", id=g["offerings"][0])
    sql(db, "UPDATE menu_dates SET menu_id=:menu WHERE service_date=:day", menu=g["other"], day=g["day"])
    assert service.create_pending(admin, original) == edited
    for changed in (replace(original, items=(ItemSelection(g["offerings"][0], 2),)),
                    replace(original, allocations=()), replace(original, service_date=date(2040, 2, 1)),
                    replace(original, employee_number=None, visitor_id=g["visitor"])):
        with pytest.raises(Conflict):
            service.create_pending(admin, changed)
    assert counts(db) == (1, 3, 2, 2, 0)


@pytest.mark.parametrize("role", ["admin", "assistant"])
def test_pending_edits_history_and_provenance(db, env, role):
    g, service, admin, assistant = env
    actor = admin if role == "admin" else assistant
    created = service.create_pending(admin, request(g))
    before = state(db, created.order_id)
    sql(db, "UPDATE menu_dates SET menu_id=:menu WHERE service_date=:day", menu=g["other"], day=g["day"])
    sql(db, "UPDATE menu_items SET unit_price=51,item_name='Synthetic revised name' WHERE id=:id", id=g["offerings"][0])
    result = service.edit_pending(actor, created.order_id, 1, EditPending(
        quantities=(QuantityChange(before["lines"][0]["id"], 2),),
        remove_line_ids=(before["lines"][1]["id"],), add_items=(ItemSelection(g["offerings"][0], 1),),
        allocations=(Allocation("sd", Decimal("196")),)))
    after = state(db, created.order_id)
    assert result.version == 2 and result.total == Decimal("196")
    assert after["order"]["menu_id"] == g["menu"] and after["order"]["service_date"] == g["day"]
    assert after["order"]["employee_number"] == g["employee"]
    assert [line["unit_price"] for line in after["lines"]] == list(map(Decimal, ("50", "15", "51")))
    assert after["lines"][0]["item_name"] == before["lines"][0]["item_name"]
    assert after["lines"][-1]["item_name"] == "Synthetic revised name"
    assert [(a["payment_category_code"], a["amount"]) for a in after["allocations"]] == [("sd", Decimal("196"))]
    assert after["audits"][1]["actor_user_id"] == actor.user_id
    assert after["audits"][1]["before_values"]["items"][1]["id"] == before["lines"][1]["id"]
    assert after["audits"][1]["before_values"]["allocations"][0]["category"] == "cash"
    assert after["audits"][1]["after_values"]["version"] == 2
    assert after["audits"][0] == before["audits"][0] and not after["receipts"]
    assert service.edit_pending(actor, created.order_id, 2, EditPending()) == result
    assert len(state(db, created.order_id)["audits"]) == 2
    with pytest.raises(Conflict):
        service.edit_pending(actor, created.order_id, 1, EditPending(allocations=()))
    assert state(db, created.order_id) == after


@pytest.mark.parametrize("field,value", [("employee_number", "forged"), ("visitor_id", 1),
    ("service_date", date(2040, 2, 1)), ("menu_id", 1), ("unit_price", Decimal("1")),
    ("customer_name_snapshot", "forged"), ("created_by", 1), ("version", 1)])
def test_sensitive_fields_are_not_edit_inputs(db, env, field, value):
    g, service, admin, _ = env
    created = service.create_pending(admin, request(g))
    before = state(db, created.order_id)
    with pytest.raises(TypeError):
        EditPending(**{field: value})
    with pytest.raises(OrderError):
        service.edit_pending(admin, created.order_id, 1, {field: value})
    assert state(db, created.order_id) == before


def test_invalid_edits_rollback_all_changes_and_preserve_ids(db, env):
    g, service, admin, assistant = env
    created = service.create_pending(admin, request(g))
    before = state(db, created.order_id)
    first = before["lines"][0]["id"]
    for changes in (
        EditPending(remove_line_ids=tuple(i["id"] for i in before["lines"])),
        EditPending(quantities=(QuantityChange(first, 0),)),
        EditPending(quantities=(QuantityChange(99999999, 2),)),
        EditPending(quantities=(QuantityChange(first, 2), QuantityChange(first, 3))),
        EditPending(remove_line_ids=(first,), quantities=(QuantityChange(first, 2),)),
        EditPending(add_items=(ItemSelection(99999999, 1),)),
        EditPending(quantities=(QuantityChange(first, 2),), allocations=(Allocation("cash", Decimal("-1")),)),
    ):
        with pytest.raises(OrderError):
            service.edit_pending(assistant, created.order_id, 1, changes)
        assert state(db, created.order_id) == before
    updated = service.edit_pending(assistant, created.order_id, 1, EditPending(
        allocations=(Allocation("cash", Decimal("200")), Allocation("sd", Decimal("45")))))
    saved = state(db, updated.order_id)
    assert saved["allocations"][0]["id"] == before["allocations"][0]["id"]
    assert saved["allocations"][0]["created_by"] == admin.user_id
    assert saved["allocations"][0]["updated_by"] == assistant.user_id
    with pytest.raises(NotFound):
        service.edit_pending(admin, 99999999, 1, EditPending())


def test_visitor_edit_and_pending_allocation_completion(db, env):
    g, service, admin, assistant = env
    created = service.create_pending(admin, request(g, employee_number=None, visitor_id=g["visitor"], allocations=()))
    before = state(db, created.order_id)
    with pytest.raises(OrderError):
        service.edit_pending(assistant, created.order_id, 1, EditPending(
            quantities=(QuantityChange(before["lines"][0]["id"], 2),), allocations=(Allocation("sd", Decimal("295")),)))
    assert state(db, created.order_id) == before
    edited = service.edit_pending(assistant, created.order_id, 1,
                                  EditPending(allocations=(Allocation("finance", Decimal("200")),)))
    marked = service.mark_received(assistant, created.order_id, edited.version)
    saved = state(db, marked.order_id)
    assert saved["order"]["is_received"]
    assert saved["allocations"][0]["amount"] == Decimal("245")


@pytest.mark.parametrize("amount", ["244.99", "245.01"])
def test_imbalance_blocks_received_without_events(db, env, amount):
    g, service, admin, _ = env
    created = service.create_pending(admin, request(g, allocations=(Allocation("cash", Decimal(amount)),)))
    before = state(db, created.order_id)
    with pytest.raises(OrderError):
        service.mark_received(admin, created.order_id, 1)
    assert state(db, created.order_id) == before


@pytest.mark.parametrize("code", list(CORRECTION_REASONS))
def test_mark_reverse_remark_history_and_current_recognition(db, env, code):
    g, service, admin, assistant = env
    created = service.create_pending(admin, request(g, allocations=(Allocation("sd", Decimal("245")),)))

    def recognized():
        # Test assertions only, not a reporting feature or item/allocation join.
        return (sql(db, "SELECT coalesce(sum(i.line_total),0) FROM order_items i JOIN orders o ON o.id=i.order_id "
                    "WHERE o.id=:id AND o.is_received", id=created.order_id).scalar_one(),
                sql(db, "SELECT coalesce(sum(a.amount),0) FROM payment_allocations a JOIN orders o ON o.id=a.order_id "
                    "WHERE o.id=:id AND o.is_received AND a.payment_category_code='sd'", id=created.order_id).scalar_one())

    assert recognized() == (0, 0)
    marked = service.mark_received(assistant, created.order_id, 1)
    first = state(db, created.order_id)
    assert recognized() == (Decimal("245"), Decimal("245"))
    assert service.mark_received(assistant, created.order_id, marked.version) == marked
    for actor in (admin, assistant):
        with pytest.raises(Conflict):
            service.edit_pending(actor, created.order_id, marked.version, EditPending(allocations=()))
    with pytest.raises(Forbidden):
        service.reverse_received(assistant, created.order_id, marked.version, Correction(code, True, "Synthetic correction"))
    reversed_order = service.reverse_received(admin, created.order_id, marked.version,
                                               Correction(code, True, "  Synthetic correction  "))
    assert recognized() == (0, 0)
    assert service.reverse_received(admin, created.order_id, reversed_order.version,
                                     Correction(code, True, "Synthetic correction")) == reversed_order
    # A stale mark cannot turn a later reversed order back to Received (ABA).
    with pytest.raises(Conflict):
        service.mark_received(assistant, created.order_id, 1)
    marked_again = service.mark_received(admin, created.order_id, reversed_order.version)
    assert marked_again.version == 4 and recognized() == (Decimal("245"), Decimal("245"))
    saved = state(db, created.order_id)
    assert [r["to_received"] for r in saved["receipts"]] == [True, False, True]
    assert len(saved["audits"]) == 4 and saved["audits"][:2] == first["audits"]
    assert saved["lines"] == first["lines"] and saved["allocations"] == first["allocations"]
    reason = saved["receipts"][1]
    assert reason["reason_code"] == code and reason["reason_label_snapshot"] == CORRECTION_REASONS[code]
    assert reason["reason_explanation"] == "Synthetic correction"
    for audit, receipt in zip(saved["audits"][1:], saved["receipts"]):
        assert audit["id"] == receipt["audit_event_id"]
        assert audit["before_values"]["is_received"] == receipt["from_received"]
        assert audit["after_values"]["is_received"] == receipt["to_received"]
    assert saved["order"]["receipt_changed_at"] == saved["audits"][-1]["occurred_at"]
    assert saved["audits"][1]["actor_user_id"] == assistant.user_id
    assert saved["audits"][2]["actor_user_id"] == admin.user_id


@pytest.mark.parametrize("correction", [Correction("unknown", True), Correction("other", True),
    Correction("other", True, " \t\n"), Correction("mistaken_click", False),
    Correction("mistaken_click", 1), Correction("other", True, 123)])
def test_invalid_correction_does_not_change_state_or_history(db, env, correction):
    g, service, admin, _ = env
    created = service.create_pending(admin, request(g))
    marked = service.mark_received(admin, created.order_id, 1)
    before = state(db, created.order_id)
    with pytest.raises(OrderError):
        service.reverse_received(admin, created.order_id, marked.version, correction)
    assert state(db, created.order_id) == before


def test_remarking_preserves_snapshots_and_reason_label_history(db, env, monkeypatch):
    g, service, admin, assistant = env
    created = service.create_pending(admin, request(g))
    marked = service.mark_received(assistant, created.order_id, 1)
    reversed_order = service.reverse_received(admin, created.order_id, marked.version,
                                               Correction("mistaken_click", True))
    before = state(db, created.order_id)
    sql(db, "UPDATE employees SET full_name='Synthetic renamed employee' WHERE employee_number=:number",
        number=g["employee"])
    sql(db, "UPDATE dishes SET category_code='non_vegetable' WHERE id=:id", id=g["dishes"][0])
    sql(db, "UPDATE menu_items SET item_name='Synthetic changed offering',unit_price=80,category_code='non_vegetable' "
        "WHERE id=:id", id=g["offerings"][0])
    sql(db, "UPDATE menu_dates SET menu_id=:menu WHERE service_date=:day", menu=g["other"], day=g["day"])
    monkeypatch.setattr("asi_meal_api.orders.CORRECTION_REASONS", {"mistaken_click": "Revised demo label"})
    remarked = service.mark_received(admin, created.order_id, reversed_order.version)
    service.reverse_received(admin, created.order_id, remarked.version, Correction("mistaken_click", True))
    after = state(db, created.order_id)
    assert after["order"]["customer_name_snapshot"] == before["order"]["customer_name_snapshot"]
    assert after["order"]["menu_id"] == before["order"]["menu_id"]
    assert after["lines"] == before["lines"] and after["allocations"] == before["allocations"]
    assert after["receipts"][1]["reason_label_snapshot"] == "Mistaken click"
    assert after["receipts"][3]["reason_label_snapshot"] == "Revised demo label"
    assert after["audits"][:3] == before["audits"]


def test_actor_boundary_disabled_missing_and_http_surface(db, env):
    g, service, admin, assistant = env
    created = service.create_pending(admin, request(g))
    before = state(db, created.order_id)
    sql(db, "UPDATE users SET is_enabled=false WHERE id=:id", id=assistant.user_id)
    for context in (assistant, ActorContext(99999999), {"user_id": admin.user_id, "role": "admin"}, None):
        with pytest.raises(Forbidden):
            service.create_pending(context, request(g))
        with pytest.raises(Forbidden):
            service.edit_pending(context, created.order_id, 1, EditPending())
        with pytest.raises(Forbidden):
            service.mark_received(context, created.order_id, 1)
        with pytest.raises(Forbidden):
            service.reverse_received(context, created.order_id, 1, Correction("mistaken_click", True))
    assert state(db, created.order_id) == before
    from asi_meal_api.main import app
    paths = app.openapi()["paths"]
    from conftest import EXPECTED_HTTP_ROUTES
    assert {path: set(operations) for path, operations in paths.items()} == EXPECTED_HTTP_ROUTES


@pytest.mark.parametrize("operation,failed_table", [("create", "audit_events"), ("edit", "audit_events"),
    ("mark", "audit_events"), ("mark", "receipt_events"), ("reverse", "receipt_events")])
def test_failed_audit_or_receipt_insert_rolls_back_whole_use_case(db, env, operation, failed_table):
    g, service, admin, _ = env
    original = request(g)
    created = None if operation == "create" else service.create_pending(admin, original)
    if operation == "reverse":
        created = service.mark_received(admin, created.order_id, 1)
    before = state(db, created.order_id) if created else counts(db)

    def fail_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith(f"INSERT INTO {failed_table} "):
            # An actual database statement failure, after earlier writes.
            cursor.execute("SELECT 1/0")

    event.listen(db, "before_cursor_execute", fail_insert)
    try:
        with pytest.raises(Exception, match="division by zero"):
            if operation == "create":
                service.create_pending(admin, original)
            elif operation == "edit":
                service.edit_pending(admin, created.order_id, created.version, EditPending(allocations=()))
            elif operation == "mark":
                service.mark_received(admin, created.order_id, created.version)
            else:
                service.reverse_received(admin, created.order_id, created.version, Correction("mistaken_click", True))
    finally:
        event.remove(db, "before_cursor_execute", fail_insert)
    assert (state(db, created.order_id) if created else counts(db)) == before


@pytest.fixture
def concurrent_env(postgres):
    # Same already-verified disposable DB, separate random schema to allow real
    # commits without leaving history that interferes with Stage 1's empty checks.
    schema = f"stage2_{uuid4().hex}"
    with postgres.engine.begin() as c:
        c.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = create_engine(postgres.engine.url, hide_parameters=True,
                           connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as c:
            assert c.exec_driver_sql("SELECT current_schema()").scalar_one() == schema
            assert inspect(c).get_table_names() == []
            command.upgrade(alembic_config(c), "head")
            g = graph(c)
        yield engine, g, OrderService(sessionmaker(bind=engine)), ActorContext(g["actor"])
    finally:
        engine.dispose()
        with postgres.engine.begin() as c:
            # Exact randomly named schema owned by this fixture only.
            c.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.mark.parametrize("conflicting", [False, True])
def test_concurrent_idempotent_creation(concurrent_env, conflicting):
    engine, g, service, admin = concurrent_env
    original = request(g)
    barrier = threading.Barrier(2)

    def create(payload):
        barrier.wait(timeout=10)
        try:
            return service.create_pending(admin, payload)
        except Conflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        alternative = replace(original, allocations=()) if conflicting else original
        futures = [pool.submit(create, payload) for payload in (original, alternative)]
        results = [f.result(timeout=15) for f in futures]
    if conflicting:
        assert results.count("conflict") == 1
    else:
        assert results[0] == results[1]
    winner = next(r for r in results if r != "conflict")
    with engine.begin() as c:
        saved = state(c, winner.order_id)
        assert counts(c) == (1, 3, len(saved["allocations"]), 1, 0)
        assert not saved["receipts"]
        expected = original if results[0] != "conflict" else alternative
        assert len(saved["allocations"]) == len(expected.allocations)


@pytest.mark.parametrize("competitor", ["mark", "edit", "reverse", "edit_edit", "edit_mark"])
def test_concurrent_transition_and_edit_reject_stale_writer(concurrent_env, competitor):
    engine, g, service, admin = concurrent_env
    created = service.create_pending(admin, request(g))
    if competitor == "reverse":
        created = service.mark_received(admin, created.order_id, 1)
    with engine.begin() as c:
        before = state(c, created.order_id)
    parent_locked = threading.Event()
    second_started = threading.Event()
    release = threading.Event()
    second_pid = []
    editing_first = competitor.startswith("edit_")

    def hold_parent(conn, cursor, statement, parameters, context, executemany):
        if threading.current_thread().name.startswith("first") and statement.startswith("SELECT orders.") and "FOR UPDATE" in statement:
            parent_locked.set()
            assert release.wait(10)

    event.listen(engine, "after_cursor_execute", hold_parent)

    def watch_second(conn, cursor, statement, parameters, context, executemany):
        if (threading.current_thread().name.startswith("second")
                and statement.startswith("SELECT orders.") and "FOR UPDATE" in statement):
            second_pid.append(conn.exec_driver_sql("SELECT pg_backend_pid()").scalar_one())
            second_started.set()

    event.listen(engine, "before_cursor_execute", watch_second)

    def first():
        if competitor == "reverse":
            return service.reverse_received(admin, created.order_id, created.version, Correction("mistaken_click", True))
        if editing_first:
            return service.edit_pending(admin, created.order_id, created.version, EditPending(allocations=()))
        return service.mark_received(admin, created.order_id, created.version)

    def second():
        try:
            if competitor in {"edit", "edit_edit"}:
                service.edit_pending(admin, created.order_id, created.version, EditPending(allocations=()))
            elif competitor == "reverse":
                service.reverse_received(admin, created.order_id, created.version, Correction("other", True, "Synthetic correction"))
            else:
                service.mark_received(admin, created.order_id, created.version)
        except Conflict:
            return "stale"
        return "unexpected success"

    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="first") as p1, ThreadPoolExecutor(max_workers=1, thread_name_prefix="second") as p2:
            f1 = p1.submit(first)
            assert parent_locked.wait(10)
            f2 = p2.submit(second)
            assert second_started.wait(10)
            # Verify actual lock contention, rather than assuming thread overlap.
            deadline = time.monotonic() + 5
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
                while time.monotonic() < deadline:
                    wait_type = sql(observer, "SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid",
                                    pid=second_pid[0]).scalar_one()
                    if wait_type == "Lock":
                        break
                    time.sleep(0.01)
                else:
                    pytest.fail("Second writer never waited on the locked order")
            assert not f2.done()
            release.set()
            result = f1.result(timeout=15)
            assert f2.result(timeout=15) == "stale"
    finally:
        release.set()
        event.remove(engine, "after_cursor_execute", hold_parent)
        event.remove(engine, "before_cursor_execute", watch_second)
    with engine.begin() as c:
        saved = state(c, created.order_id)
        assert saved["order"]["version"] == created.version + 1 == result.version
        assert saved["order"]["is_received"] == (competitor != "reverse" and not editing_first)
        assert len(saved["audits"]) == len(before["audits"]) + 1
        assert len(saved["receipts"]) == len(before["receipts"]) + (0 if editing_first else 1)
        assert saved["lines"] == before["lines"]
        assert saved["allocations"] == ([] if editing_first else before["allocations"])
