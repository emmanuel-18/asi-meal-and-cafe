"""Operational reports: synthetic committed data in verified disposable schemas."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from decimal import Decimal
import threading
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from asi_meal_api.employee_imports import EmployeeImportService
from asi_meal_api.orders import ActorContext, Allocation, Correction, CreateOrder, EditPending, Forbidden, ItemSelection, QuantityChange
from asi_meal_api.reports import DateRange, ReportInputError, ReportingService
from test_database import sql
from test_employee_imports import csv_bytes, person
from test_orders import concurrent_env


@pytest.fixture
def env(concurrent_env):
    engine, graph, orders, admin = concurrent_env
    with engine.begin() as c:
        assistant = sql(c, "INSERT INTO users (login_name,display_name,password_hash,role_code) "
                        "SELECT :login,'Synthetic Assistant',password_hash,'assistant_admin' FROM users "
                        "WHERE id=:id RETURNING id", login=uuid4().hex, id=admin.user_id).scalar_one()
    factory = sessionmaker(bind=engine)
    return engine, graph, orders, ReportingService(factory), admin, ActorContext(assistant), factory


def make_order(env, *, day=None, items=None, allocations=None, received=True, visitor=False, employee=None):
    engine, g, orders, _, admin, _, _ = env
    day = day or g["day"]
    with engine.begin() as c:
        sql(c, "INSERT INTO menu_dates (service_date,menu_id) VALUES (:day,:menu) ON CONFLICT DO NOTHING",
            day=day, menu=g["menu"])
    if items is None:
        items = tuple(ItemSelection(item, quantity) for item, quantity in zip(g["offerings"], (1, 2, 3)))
    if allocations is None:
        allocations = (Allocation("finance" if visitor else "cash", Decimal("245")),)
    order = orders.create_pending(admin, CreateOrder(uuid4(), day, g["menu"], items, allocations,
        employee_number=None if visitor else (employee or g["employee"]), visitor_id=g["visitor"] if visitor else None))
    return orders.mark_received(admin, order.order_id, order.version) if received else order


def amounts(payments):
    return {row.category: row.amount for row in payments}


def assert_reconciles(bundle, expected):
    assert bundle.sales.recognized_sales == bundle.payments.total == Decimal(expected)
    assert bundle.sales.allocated_total == bundle.payments.total
    assert bundle.sales.reconciles and bundle.sales.allocation_difference == Decimal("0.00")
    assert sum((item.amount for item in bundle.sales.items), Decimal(0)) == Decimal(expected)
    assert sum((item.amount for item in bundle.sales.categories), Decimal(0)) == Decimal(expected)
    assert bundle.salary_deduction.total == amounts(bundle.payments.totals)["sd"]
    assert sum((row.sd_amount for row in bundle.salary_deduction.employees), Decimal(0)) == bundle.salary_deduction.total
    assert sum((row.sd_amount for row in bundle.salary_deduction.orders), Decimal(0)) == bundle.salary_deduction.total


def test_empty_pending_and_split_aggregates_do_not_multiply(env):
    _, g, _, reports, admin, assistant, _ = env
    period = DateRange.daily(g["day"])
    empty = reports.report_bundle(admin, period)
    assert_reconciles(empty, "0")
    assert empty.sales.received_order_count == empty.sales.item_quantity == empty.sales.meal_quantity == 0
    assert empty.sales.items == empty.salary_deduction.orders == empty.salary_deduction.employees == ()
    assert amounts(empty.payments.totals) == dict.fromkeys(("cash", "gcash", "sd", "incentive", "finance"), Decimal(0))
    make_order(env, received=False)
    assert reports.report_bundle(admin, period) == empty
    make_order(env, allocations=(Allocation("cash", Decimal("45")), Allocation("gcash", Decimal("100")), Allocation("sd", Decimal("100"))))
    make_order(env, items=(ItemSelection(g["offerings"][0], 1),), allocations=(Allocation("sd", Decimal("50")),))
    make_order(env, items=(ItemSelection(g["offerings"][1], 1),), allocations=(Allocation("finance", Decimal("75")),), visitor=True)
    make_order(env, items=(ItemSelection(g["offerings"][0], 1),), allocations=(Allocation("cash", Decimal("50")),))
    make_order(env, items=(ItemSelection(g["offerings"][2], 1),), allocations=(Allocation("incentive", Decimal("15")),))
    bundle = reports.report_bundle(assistant, period)
    assert_reconciles(bundle, "435")
    assert bundle.sales.received_order_count == 5
    assert bundle.sales.item_quantity == 10 and bundle.sales.meal_quantity == 6
    assert {c.category: (c.quantity, c.amount) for c in bundle.sales.categories} == {
        "vegetable": (3, Decimal("150")), "non_vegetable": (3, Decimal("225")), "extra_rice": (4, Decimal("60"))}
    assert amounts(bundle.payments.totals) == {"cash": Decimal("95"), "gcash": Decimal("100"), "sd": Decimal("150"),
                                             "incentive": Decimal("15"), "finance": Decimal("75")}
    assert len(bundle.salary_deduction.employees) == 1
    assert bundle.salary_deduction.employees[0].employee_number == g["employee"]
    assert bundle.salary_deduction.employees[0].order_count == 2
    assert bundle.salary_deduction.employees[0].sd_amount == Decimal("150")
    assert len(bundle.salary_deduction.orders) == 2
    assert reports.sales_summary(admin, period) == bundle.sales
    assert reports.payment_summary(admin, period) == bundle.payments
    assert reports.salary_deduction_report(admin, period) == bundle.salary_deduction
    assert all(isinstance(row.amount, Decimal) for row in bundle.payments.totals)
    assert all(isinstance(row.amount, Decimal) and isinstance(row.unit_price, Decimal) for row in bundle.sales.items)


def test_reversal_and_remarking_restore_once(env):
    _, g, orders, reports, admin, assistant, _ = env
    order = make_order(env, allocations=(Allocation("sd", Decimal("200")), Allocation("cash", Decimal("45"))))
    period = DateRange.daily(g["day"])
    original = reports.report_bundle(admin, period)
    assert_reconciles(original, "245")
    reversed_order = orders.reverse_received(admin, order.order_id, order.version, Correction("mistaken_click", True))
    assert_reconciles(reports.report_bundle(assistant, period), "0")
    remarked = orders.mark_received(assistant, order.order_id, reversed_order.version)
    assert reports.report_bundle(admin, period) == original
    orders.mark_received(admin, order.order_id, remarked.version)
    assert reports.report_bundle(admin, period) == original


def test_historical_item_and_customer_snapshots_remain_visible(env):
    engine, g, _, reports, admin, _, factory = env
    original = make_order(env, allocations=(Allocation("sd", Decimal("245")),))
    before = reports.report_bundle(admin, DateRange.daily(g["day"]))
    imported = EmployeeImportService(factory).import_csv(admin, csv_bytes([
        person(g["employee"], "Synthetic New Name", position="Synthetic New Position", campaign="Synthetic New Campaign", line_of_business="Synthetic New LOB"),
        person("SYN-SECOND", "Synthetic New Name")]))
    assert imported.status == "completed"
    with engine.begin() as c:
        sql(c, "UPDATE dishes SET name='Synthetic New Catalog',category_code='non_vegetable' WHERE id=:id", id=g["dishes"][0])
        sql(c, "UPDATE menu_items SET item_name='Synthetic New Offering',category_code='non_vegetable',unit_price=80 WHERE id=:id", id=g["offerings"][0])
    assert reports.report_bundle(admin, DateRange.daily(g["day"])) == before
    make_order(env, items=(ItemSelection(g["offerings"][0], 1),), allocations=(Allocation("sd", Decimal("80")),))
    make_order(env, items=(ItemSelection(g["offerings"][2], 1),), allocations=(Allocation("sd", Decimal("15")),), employee="SYN-SECOND")
    after = reports.report_bundle(admin, DateRange.daily(g["day"]))
    assert_reconciles(after, "340")
    assert len(after.salary_deduction.employees) == 2  # Equal names never merge identities.
    employee = next(e for e in after.salary_deduction.employees if e.employee_number == g["employee"])
    assert employee.order_count == 2 and employee.sd_amount == Decimal("325")
    old = next(row for row in after.salary_deduction.orders if row.order_id == original.order_id)
    assert old == before.salary_deduction.orders[0]
    new = next(row for row in after.salary_deduction.orders if row.employee_number == g["employee"] and row.order_id != original.order_id)
    assert (new.customer_name, new.position, new.campaign, new.line_of_business) == (
        "Synthetic New Name", "Synthetic New Position", "Synthetic New Campaign", "Synthetic New LOB")
    assert len(after.sales.items) == 4
    original_item = next(i for i in after.sales.items if i.source_menu_item_id == g["offerings"][0] and i.unit_price == Decimal("50"))
    assert original_item.item_name == before.sales.items[0].item_name and original_item.category == "vegetable"
    assert original_item.quantity == 1 and original_item.amount == Decimal("50")


def test_service_date_daily_weekly_monthly_and_inclusive_custom_ranges(env):
    engine, g, _, reports, admin, _, _ = env
    days = [date(2028, 1, 31), date(2028, 2, 1), date(2028, 2, 27), date(2028, 2, 28),
            date(2028, 2, 29), date(2028, 3, 1), date(2028, 3, 5), date(2028, 3, 6)]
    for day in days:
        make_order(env, day=day, items=(ItemSelection(g["offerings"][0], 1),), allocations=(Allocation("sd", Decimal("50")),))
    cases = [(DateRange.daily(date(2028, 2, 29)), 1), (DateRange.weekly(date(2028, 3, 1)), 4),
             (DateRange.monthly(2028, 2), 4), (DateRange(date(2028, 2, 29), date(2028, 3, 1)), 2),
             (DateRange.weekly(date(2028, 3, 6)), 1), (DateRange.daily(date(2028, 3, 7)), 0)]
    for period, count in cases:
        bundle = reports.report_bundle(admin, period)
        assert_reconciles(bundle, str(count * 50))
        assert bundle.sales.received_order_count == count
        assert all(period.start <= order.service_date <= period.end for order in bundle.salary_deduction.orders)
    assert DateRange.weekly(date(2028, 3, 1)) == DateRange(date(2028, 2, 28), date(2028, 3, 5))
    with engine.connect() as c:
        # Recording timestamps stay unchanged and do not decide report periods.
        assert sql(c, "SELECT bool_and(extract(year FROM recorded_at) <> 2028) FROM orders").scalar_one()


@pytest.mark.parametrize("operation", [
    lambda: DateRange("2028-01-01", date(2028, 1, 2)),
    lambda: DateRange(date(2028, 1, 1), None),
    lambda: DateRange(date(2028, 1, 2), date(2028, 1, 1)),
    lambda: DateRange.daily(datetime(2028, 1, 1)),
    lambda: DateRange.weekly("2028-01-01"), lambda: DateRange.weekly(date.max),
    lambda: DateRange.monthly(2028, 0), lambda: DateRange.monthly(2028, 13),
    lambda: DateRange.monthly(0, 1), lambda: DateRange.monthly(10000, 1),
    lambda: DateRange.monthly("2028", 1), lambda: DateRange.monthly(2028, True),
])
def test_invalid_calendar_inputs(operation):
    with pytest.raises(ReportInputError):
        operation()


def test_calendar_month_and_year_boundaries():
    assert DateRange.monthly(2028, 2) == DateRange(date(2028, 2, 1), date(2028, 2, 29))
    assert DateRange.monthly(2027, 2).end == date(2027, 2, 28)
    assert DateRange.monthly(2026, 12).end == date(2026, 12, 31)
    assert DateRange.weekly(date(2027, 1, 1)) == DateRange(date(2026, 12, 28), date(2027, 1, 3))


def test_authorization_read_only_snapshot_and_connection_reset(env):
    engine, g, _, reports, admin, assistant, _ = env
    make_order(env)
    period = DateRange.daily(g["day"])
    properties = []

    def inspect_read(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT users."):
            properties.append((conn.exec_driver_sql("SHOW transaction_isolation").scalar_one(),
                               conn.exec_driver_sql("SHOW transaction_read_only").scalar_one()))

    with engine.connect() as c:
        before = sql(c, "SELECT count(*) FROM audit_events").scalar_one()
    event.listen(engine, "after_cursor_execute", inspect_read)
    try:
        assert reports.report_bundle(admin, period) == reports.report_bundle(assistant, period)
    finally:
        event.remove(engine, "after_cursor_execute", inspect_read)
    assert properties == [("repeatable read", "on"), ("repeatable read", "on")]
    with engine.begin() as c:
        assert sql(c, "SELECT count(*) FROM audit_events").scalar_one() == before
        assert c.exec_driver_sql("SHOW transaction_isolation").scalar_one() == "read committed"
        assert c.exec_driver_sql("SHOW transaction_read_only").scalar_one() == "off"
        sql(c, "UPDATE users SET is_enabled=false WHERE id=:id", id=assistant.user_id)
    for method in (reports.sales_summary, reports.payment_summary, reports.salary_deduction_report, reports.report_bundle):
        for actor in (assistant, ActorContext(99999999), ActorContext(True), {"user_id": admin.user_id, "role": "admin"}, None):
            with pytest.raises(Forbidden):
                method(actor, period)
        with pytest.raises(ReportInputError):
            method(admin, (g["day"], g["day"]))


@pytest.mark.parametrize("change", ["reverse", "mark", "correct"])
def test_concurrent_reports_keep_one_snapshot_and_next_call_reflects_changes(env, change):
    engine, g, orders, reports, admin, _, _ = env
    order = make_order(env, received=change != "mark", allocations=(Allocation("sd", Decimal("245")),))
    period = DateRange.daily(g["day"])
    payments_read = threading.Event()
    release = threading.Event()

    def pause(conn, cursor, statement, parameters, context, executemany):
        if (threading.current_thread().name.startswith("report")
                and "GROUP BY payment_allocations.payment_category_code" in statement):
            payments_read.set()
            assert release.wait(10)

    def update():
        if change == "mark":
            return orders.mark_received(admin, order.order_id, order.version)
        pending = orders.reverse_received(admin, order.order_id, order.version, Correction("incorrect_order_details", True))
        if change == "correct":
            with engine.connect() as c:
                line = sql(c, "SELECT id FROM order_items WHERE order_id=:id ORDER BY line_number LIMIT 1", id=order.order_id).scalar_one()
            edited = orders.edit_pending(admin, order.order_id, pending.version,
                EditPending(quantities=(QuantityChange(line, 2),), allocations=(Allocation("sd", Decimal("295")),)))
            return orders.mark_received(admin, order.order_id, edited.version)
        return pending

    event.listen(engine, "after_cursor_execute", pause)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="report") as reader, ThreadPoolExecutor(max_workers=1) as writer:
            read = reader.submit(reports.report_bundle, admin, period)
            try:
                assert payments_read.wait(10)
                writer.submit(update).result(timeout=10)
            finally:
                release.set()
            old_snapshot = read.result(timeout=10)
    finally:
        release.set()
        event.remove(engine, "after_cursor_execute", pause)
    assert_reconciles(old_snapshot, "0" if change == "mark" else "245")
    assert_reconciles(reports.report_bundle(admin, period), {"mark": "245", "reverse": "0", "correct": "295"}[change])
