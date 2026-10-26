"""Read-only export detail contracts on the verified disposable PostgreSQL harness."""

from dataclasses import asdict, replace
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event

from asi_meal_api.business_services import BusinessService
from asi_meal_api.orders import ActorContext, Allocation, Correction, CreateOrder, Forbidden, ItemSelection
from asi_meal_api.reports import MAX_EXPORT_DAYS, DateRange, ReportInputError, ReportReconciliationError, ReportingService
from test_auth import auth_env, client, login_http, passwords
from test_database import sql
from test_orders import concurrent_env
from test_reports import env, make_order


def detailed(env, period=None, actor=None):
    _, g, _, reports, admin, _, _ = env
    return reports.report_bundle(actor or admin, period or DateRange.daily(g["day"]), include_export_details=True)


def check(bundle):
    details = bundle.export_details
    assert details.period == bundle.sales.period == bundle.payments.period == bundle.salary_deduction.period
    assert sum((o.total for o in details.orders), Decimal(0)) == bundle.sales.recognized_sales
    assert len(details.orders) == bundle.sales.received_order_count
    assert sum((i.line_total for o in details.orders for i in o.items), Decimal(0)) == bundle.sales.recognized_sales
    assert sum((p.amount for o in details.orders for p in o.allocations), Decimal(0)) == bundle.payments.total
    assert sum((d.recognized_sales for d in details.daily), Decimal(0)) == bundle.sales.recognized_sales
    assert all(d.allocation_difference == Decimal(0) for d in details.daily)
    assert all(tuple(p.category for p in d.payments) == ("cash", "gcash", "sd", "incentive", "finance") for d in details.daily)
    assert sum((c.sd_amount for c in details.sd_campaigns), Decimal(0)) == bundle.salary_deduction.total
    assert all(e.sd_amount > 0 for e in bundle.salary_deduction.employees)
    for order in details.orders:
        assert sum((i.line_total for i in order.items), Decimal(0)) == order.total
        assert sum((p.amount for p in order.allocations), Decimal(0)) == order.total
        assert all(i.line_total == i.unit_price * i.quantity for i in order.items)
        if order.customer_type == "visitor":
            assert order.employee_number is None and order.visitor_id is not None
            assert [p.category for p in order.allocations] == ["finance"]


def test_details_employee_visitor_splits_sd_and_privacy(env):
    engine, g, _, _, admin, assistant, _ = env
    number = "000" + "7" * 160
    name, campaign = "Synthetic ñ 長 name " * 30, "Synthetic campaign " * 20
    with engine.begin() as c:
        sql(c, "INSERT INTO employees (employee_number,full_name,position,campaign,line_of_business,last_import_id) "
            "VALUES (:number,:name,'Synthetic role',:campaign,'Synthetic LOB',:job)",
            number=number, name=name, campaign=campaign, job=g["job"])
    make_order(env, employee=number, allocations=(Allocation("cash", Decimal("45")), Allocation("gcash", Decimal("200"))))
    make_order(env, employee=number, allocations=tuple(Allocation(code, Decimal(amount)) for code, amount in
        [("cash", "10"), ("gcash", "10"), ("sd", "100"), ("incentive", "25"), ("finance", "100")]))
    visitor = make_order(env, visitor=True)
    make_order(env, received=False)
    bundle = detailed(env, actor=assistant)
    assert bundle == detailed(env, actor=admin)
    check(bundle)
    assert bundle.sales.recognized_sales == Decimal("735.00")
    assert bundle.sales.meal_quantity == 9 and bundle.sales.item_quantity == 18
    assert len(bundle.export_details.orders) == 3
    employee = bundle.export_details.orders[0]
    assert (employee.employee_number, employee.customer_name, employee.campaign) == (number, name, campaign)
    assert (employee.position, employee.line_of_business) == ("Synthetic role", "Synthetic LOB")
    assert any(i.category == "extra_rice" and i.quantity == 3 for i in employee.items)
    assert bundle.export_details.orders[-1].order_id == visitor.order_id
    assert [(e.employee_number, e.sd_amount) for e in bundle.salary_deduction.employees] == [(number, Decimal("100.00"))]
    assert [(c.campaign, c.sd_amount) for c in bundle.export_details.sd_campaigns] == [(campaign, Decimal("100.00"))]
    public = asdict(employee)
    assert set(public) == {"order_id", "service_date", "menu_id", "customer_type", "employee_number", "visitor_id",
        "customer_name", "position", "campaign", "line_of_business", "items", "allocations", "total"}
    assert "request_key" not in public and "created_by" not in public


def test_export_calendar_periods_and_empty_dates(env):
    _, g, _, _, _, _, _ = env
    for day in [date(2028, 1, 31), date(2028, 2, 1), date(2028, 2, 27), date(2028, 2, 28),
                date(2028, 2, 29), date(2028, 3, 1), date(2028, 3, 5), date(2028, 3, 6)]:
        make_order(env, day=day, allocations=(Allocation("sd", Decimal("245")),))
    cases = [(DateRange.daily(date(2028, 2, 29)), 1), (DateRange.weekly(date(2028, 3, 1)), 4),
             (DateRange.monthly(2028, 2), 4), (DateRange(date(2028, 2, 29), date(2028, 3, 1)), 2),
             (DateRange.daily(date(2028, 3, 7)), 0)]
    for period, count in cases:
        bundle = detailed(env, period)
        check(bundle)
        assert len(bundle.export_details.orders) == count
        assert len(bundle.export_details.daily) == (period.end - period.start).days + 1
        assert bundle.export_details.daily[0].service_date == period.start
        assert bundle.export_details.daily[-1].service_date == period.end
        assert all(period.start <= order.service_date <= period.end for order in bundle.export_details.orders)
    empty = detailed(env, cases[-1][0]).export_details
    assert not empty.orders and not empty.menus and not empty.sd_campaigns
    assert empty.menu_dates[0].assigned_menu_id is None
    assert empty.menu_dates[0].recorded_menu_ids == ()
    assert empty.daily[0].recognized_sales == Decimal("0.00")
    assert all(p.amount == Decimal("0.00") for p in empty.daily[0].payments)


def test_recorded_menus_prices_customer_snapshots_and_centavos(env):
    engine, g, orders, _, admin, _, factory = env
    with engine.begin() as c:
        sql(c, "UPDATE menu_items SET unit_price=50.01 WHERE id=:id", id=g["offerings"][0])
        sql(c, "UPDATE employees SET campaign='Original campaign',position='Original role' WHERE employee_number=:number", number=g["employee"])
    first = make_order(env, items=(ItemSelection(g["offerings"][0], 3),), allocations=(Allocation("sd", Decimal("150.03")),))
    recorded = detailed(env).export_details.orders[0]
    with engine.begin() as c:
        sql(c, "UPDATE menu_items SET unit_price=60.02,item_name='New saved offering' WHERE id=:id", id=g["offerings"][0])
        sql(c, "UPDATE dishes SET name='New catalog name' WHERE id=:id", id=g["dishes"][0])
        sql(c, "UPDATE employees SET full_name='New directory name',campaign='New campaign',position='New role' WHERE employee_number=:number", number=g["employee"])
    second = make_order(env, items=(ItemSelection(g["offerings"][0], 1),), allocations=(Allocation("sd", Decimal("60.02")),))
    business = BusinessService(factory)
    menu = business.create_menu(admin, "Synthetic replacement", [g["dishes"][1]], [], include_default_rice=True)
    next_day = g["day"] + timedelta(days=1)
    business.assign_menu(admin, menu["id"], [(g["day"], g["menu"]), (next_day, None)])
    new_items = tuple(ItemSelection(i["id"], 1) for i in menu["items"])
    total = sum((Decimal(i["unit_price"]) for i in menu["items"]), Decimal(0))
    third = orders.create_pending(admin, CreateOrder(uuid4(), next_day, menu["id"], new_items,
        (Allocation("cash", total),), employee_number=g["employee"]))
    orders.mark_received(admin, third.order_id, third.version)
    bundle = detailed(env, DateRange(g["day"], next_day))
    check(bundle)
    assert bundle.export_details.orders[0] == recorded
    assert {i.unit_price for o in bundle.export_details.orders[:2] for i in o.items} == {Decimal("50.01"), Decimal("60.02")}
    assert [o.order_id for o in bundle.export_details.orders] == [first.order_id, second.order_id, third.order_id]
    assert bundle.export_details.menu_dates[0].assigned_menu_id == menu["id"]
    assert bundle.export_details.menu_dates[0].recorded_menu_ids == (g["menu"],)
    assert bundle.export_details.menu_dates[1].recorded_menu_ids == (menu["id"],)
    assert {m.menu_id for m in bundle.export_details.menus} == {g["menu"], menu["id"]}
    assert {i.category for i in bundle.export_details.orders[-1].items} == {"non_vegetable", "extra_rice"}
    assert [(c.campaign, c.sd_amount) for c in bundle.export_details.sd_campaigns] == [
        ("New campaign", Decimal("60.02")), ("Original campaign", Decimal("150.03"))]


def test_reversal_remarking_and_no_zero_sd_employees(env):
    _, g, orders, _, admin, _, _ = env
    order = make_order(env, allocations=(Allocation("sd", Decimal("245")),))
    original = detailed(env)
    pending = orders.reverse_received(admin, order.order_id, order.version, Correction("mistaken_click", True))
    empty = detailed(env)
    check(empty)
    assert not empty.export_details.orders and not empty.salary_deduction.employees
    orders.mark_received(admin, order.order_id, pending.version)
    assert detailed(env) == original


def test_complete_data_constant_queries_read_only_and_no_audit_writes(env):
    engine, g, _, _, _, _, _ = env

    def measure():
        statements = []
        properties = []
        def observe(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
            if statement.startswith("SELECT users."):
                properties.append((conn.exec_driver_sql("SHOW transaction_isolation").scalar_one(),
                                   conn.exec_driver_sql("SHOW transaction_read_only").scalar_one()))
        event.listen(engine, "after_cursor_execute", observe)
        try:
            bundle = detailed(env)
        finally:
            event.remove(engine, "after_cursor_execute", observe)
        assert any(s == "SET TRANSACTION READ ONLY" for s in statements)
        assert properties == [("repeatable read", "on")]
        assert not any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements)
        return bundle, len(statements)

    _, empty_queries = measure()
    for _ in range(105):
        make_order(env)
    with engine.connect() as c:
        before = sql(c, "SELECT count(*) FROM audit_events").scalar_one()
    bundle, populated_queries = measure()
    check(bundle)
    assert len(bundle.export_details.orders) == 105
    assert len({o.order_id for o in bundle.export_details.orders}) == 105
    assert bundle.sales.recognized_sales == Decimal("25725.00")
    assert populated_queries == empty_queries
    with engine.connect() as c:
        assert sql(c, "SELECT count(*) FROM audit_events").scalar_one() == before


@pytest.mark.parametrize("field", ["recognized_sales", "received_order_count", "item_quantity", "meal_quantity", "items", "categories", "payments", "allocated_total", "allocation_difference"])
def test_export_refuses_mismatched_authoritative_sales(env, monkeypatch, field):
    _, _, _, reports, _, _, _ = env
    make_order(env)
    original = reports._sales
    def corrupt(*args):
        summary = original(*args)
        value = getattr(summary, field)
        if field in {"items", "categories", "payments"}:
            value = ()
        else:
            value += 1
        return replace(summary, **{field: value})
    monkeypatch.setattr(reports, "_sales", corrupt)
    with pytest.raises(ReportReconciliationError, match="could not be reconciled"):
        detailed(env)


@pytest.mark.parametrize("field", ["total", "orders", "employees"])
def test_export_refuses_mismatched_sd(env, monkeypatch, field):
    _, _, _, reports, _, _, _ = env
    make_order(env, allocations=(Allocation("sd", Decimal("245")),))
    original = reports._sd
    def corrupt(*args):
        result = original(*args)
        return replace(result, **{field: result.total + 1 if field == "total" else ()})
    monkeypatch.setattr(reports, "_sd", corrupt)
    with pytest.raises(ReportReconciliationError):
        detailed(env)


def test_range_resource_limit_is_explicit_and_does_not_change_regular_reports(env):
    _, g, _, reports, admin, _, _ = env
    period = DateRange(g["day"], g["day"] + timedelta(days=MAX_EXPORT_DAYS))
    with pytest.raises(ReportInputError, match="at most 3660"):
        detailed(env, period)
    assert reports.report_bundle(admin, period).sales.recognized_sales == Decimal("0.00")


def test_export_rechecks_actor_state_and_rejects_untrusted_context(env):
    engine, g, _, _, admin, assistant, _ = env
    for actor in (ActorContext(999999999), ActorContext(True), {"user_id": admin.user_id}, None):
        with pytest.raises(Forbidden):
            env[3].report_bundle(actor, DateRange.daily(g["day"]), include_export_details=True)
    for setting in ("password_change_required=true", "is_enabled=false"):
        with engine.begin() as c:
            sql(c, "UPDATE users SET password_change_required=false,is_enabled=true WHERE id=:id", id=assistant.user_id)
            sql(c, f"UPDATE users SET {setting} WHERE id=:id", id=assistant.user_id)
        with pytest.raises(Forbidden):
            detailed(env, actor=assistant)


@pytest.mark.parametrize("field", ["total", "totals"])
def test_export_refuses_mismatched_payment_summary(env, monkeypatch, field):
    reports = env[3]
    make_order(env)
    original = reports._payments
    def corrupt(*args):
        summary = original(*args)
        return replace(summary, **{field: summary.total + Decimal("0.01") if field == "total" else ()})
    monkeypatch.setattr(reports, "_payments", corrupt)
    with pytest.raises(ReportReconciliationError):
        detailed(env)


@pytest.mark.parametrize("role", ["admin", "assistant_admin", "super_admin"])
def test_http_opt_in_preserves_default_response_and_search_cannot_filter(auth_env, role):
    engine, g, orders, _, password, _, runtime = auth_env
    with engine.begin() as c:
        sql(c, "UPDATE users SET role_code=:role WHERE id=:id", role=role, id=g["actor"])
        sql(c, "INSERT INTO employees (employee_number,full_name,last_import_id) "
            "VALUES ('00001234','Synthetic leading zero',:job)", job=g["job"])
    order = orders.create_pending(ActorContext(g["actor"]), CreateOrder(uuid4(), g["day"], g["menu"],
        (ItemSelection(g["offerings"][0], 1),), (Allocation("sd", Decimal("50")),), employee_number="00001234"))
    orders.mark_received(ActorContext(g["actor"]), order.order_id, order.version)
    path = "/api/reports/bundle?mode=daily&day=2040-01-02"
    with client(runtime) as c:
        assert c.get(path + "&include_export_details=true").status_code == 401
        assert login_http(c, password).status_code == 200
        basic = c.get(path)
        assert basic.status_code == 200 and set(basic.json()) == {"sales", "payments", "salary_deduction"}
        response = c.get(path + "&include_export_details=true&q=nonexistent&employee_number=unknown&limit=1&offset=999")
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        data = response.json()
        assert {key: value for key, value in data.items() if key != "export_details"} == basic.json()
        exported = data["export_details"]["orders"]
        assert len(exported) == 1 and exported[0]["order_id"] == order.order_id
        assert exported[0]["employee_number"] == "00001234"
        assert exported[0]["total"] == "50.00" and exported[0]["items"][0]["unit_price"] == "50.00"
        for query in ("mode=weekly&day=2040-01-02", "mode=monthly&year=2040&month=1",
                      "mode=custom&start=2040-01-01&end=2040-01-03"):
            result = c.get("/api/reports/bundle?" + query + "&include_export_details=true")
            assert result.status_code == 200
            assert result.json()["export_details"]["orders"] == exported
        assert c.get(path + "&include_export_details=invalid").status_code == 422
        with engine.begin() as conn:
            sql(conn, "UPDATE users SET is_enabled=false WHERE id=:id", id=g["actor"])
        assert c.get(path + "&include_export_details=true").status_code == 401


def test_http_reconciliation_failure_is_safe_no_partial_data(auth_env, monkeypatch):
    _, _, _, _, password, _, runtime = auth_env
    def fail(*args):
        raise ReportReconciliationError("Synthetic private employee diagnostic")
    monkeypatch.setattr(ReportingService, "_export_details", fail)
    with client(runtime) as c:
        login_http(c, password)
        response = c.get("/api/reports/bundle?mode=daily&day=2040-01-02&include_export_details=true")
        assert response.status_code == 409
        assert response.json()["code"] == "REPORT_RECONCILIATION_FAILED"
        assert "private" not in response.text and "export_details" not in response.json()
