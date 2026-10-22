"""Synthetic real-session HTTP integration on the verified PostgreSQL harness."""

from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from asi_meal_api.business_services import BusinessService
from asi_meal_api import business_schemas as schemas
from asi_meal_api.auth_http import admin_actor, authenticated_actor
from asi_meal_api.business_http import directory_router, menu_router, order_router, report_router
from asi_meal_api.main import create_app
from asi_meal_api.orders import ActorContext, Forbidden
from conftest import EXPECTED_HTTP_ROUTES
from test_auth import auth_env, client, login_http, passwords
from test_orders import concurrent_env, state
from test_database import sql
from test_employee_imports import csv_bytes, person


def test_protected_route_dependencies_and_strict_input_contracts():
    paths = create_app().openapi()["paths"]
    assert {p: set(v) for p, v in paths.items()} == EXPECTED_HTTP_ROUTES
    for router in (directory_router, menu_router, order_router, report_router):
        for route in router.routes:
            calls = {dependency.call for dependency in route.dependant.dependencies}
            assert calls & {authenticated_actor, admin_actor}, route.path
    for value in (1.5, True, "NaN", "Infinity", "1.001", "10000000000"):
        with pytest.raises(ValidationError):
            schemas.AllocationIn(category="cash", amount=value)
    assert schemas.AllocationIn(category="cash", amount="1.25").amount.as_tuple().exponent == -2
    for data in ({"display_name": "   "}, {"display_name": "Synthetic", "actor_id": 1},
                 {"display_name": "Synthetic\x00"}):
        with pytest.raises(ValidationError):
            schemas.VisitorIn(**data)


def headers(csrf):
    return {"Origin": "https://testserver", "X-CSRF-Token": csrf}


def order_body(g, **changes):
    return {"request_key": str(uuid4()), "service_date": g["day"].isoformat(), "menu_id": g["menu"],
            "employee_number": g["employee"], "items": [{"menu_item_id": i, "quantity": n}
            for i, n in zip(g["offerings"], [1, 2, 3])],
            "allocations": [{"category": "gcash", "amount": "200.00"}, {"category": "sd", "amount": "45.00"}], **changes}


def requests(g):
    return [
        ("GET", "/api/employees", None), ("POST", "/api/employees/import", None),
        ("GET", "/api/visitors", None), ("POST", "/api/visitors", {"display_name": "Synthetic Guest"}),
        ("PATCH", f'/api/visitors/{g["visitor"]}', {"display_name": "Synthetic Renamed", "expected_name": "Synthetic Visitor"}),
        ("DELETE", f'/api/visitors/{g["visitor"]}', {"expected_name": "Synthetic Visitor"}),
        ("GET", "/api/dishes", None), ("POST", "/api/dishes", {"name": "Synthetic Dish", "category_code": "vegetable"}),
        ("PATCH", f'/api/dishes/{g["dishes"][0]}', {"name": "Synthetic New", "category_code": "vegetable", "expected_name": "Synthetic vegetable", "expected_category": "vegetable"}),
        ("DELETE", f'/api/dishes/{g["dishes"][0]}', {"expected_name": "Synthetic vegetable", "expected_category": "vegetable"}),
        ("GET", "/api/menu-defaults", None),
        ("POST", "/api/menus", {"dish_ids": [g["dishes"][0]]}),
        ("PUT", f'/api/menus/{g["menu"]}/dates', {"assignments": [{"service_date": "2040-01-03", "expected_menu_id": None}]}),
        ("GET", "/api/menus/by-date/2040-01-02", None), ("GET", "/api/orders", None),
        ("GET", f'/api/menus/{g["menu"]}', None),
        ("POST", "/api/orders", order_body(g)), ("GET", "/api/orders/1", None),
        ("PATCH", "/api/orders/1", {"expected_version": 1}),
        ("POST", "/api/orders/1/received", {"expected_version": 1}),
        ("POST", "/api/orders/1/reverse-received", {"expected_version": 1, "reason_code": "mistaken_click", "acknowledged": True}),
        *[("GET", f"/api/reports/{kind}?mode=daily&day=2040-01-02", None)
          for kind in ("sales", "payments", "salary-deduction", "bundle")],
    ]


def test_exact_surface_anonymous_denial_and_csrf_every_mutation(auth_env):
    _, g, _, _, password, _, runtime = auth_env
    with client(runtime) as c:
        paths = c.get("/openapi.json").json()["paths"]
        assert {p: set(v) for p, v in paths.items()} == EXPECTED_HTTP_ROUTES
        for method, url, body in requests(g):
            denied = c.request(method, url, json=body, headers={"Origin": "https://testserver"})
            assert denied.status_code == 401, (method, url, denied.text)
            assert denied.headers["cache-control"] == "no-store"
        csrf = login_http(c, password).json()["csrf_token"]
        for method, url, body in requests(g):
            if method == "GET":
                continue
            for security in ({}, {"Origin": "https://testserver"}, headers("invalid"),
                             {"Origin": "https://elsewhere.invalid", "X-CSRF-Token": csrf}):
                denied = c.request(method, url, json=body, headers=security)
                assert denied.status_code == 403, (method, url, denied.text)


@pytest.mark.parametrize("role", ["admin", "assistant_admin"])
def test_routine_catalog_visitors_orders_and_reports_both_roles(auth_env, role):
    engine, g, _, _, password, _, runtime = auth_env
    with engine.begin() as connection:
        sql(connection, "UPDATE users SET role_code=:role WHERE id=:id", role=role, id=g["actor"])
    with client(runtime) as c:
        h = headers(login_http(c, password).json()["csrf_token"])
        assert c.get("/api/employees").status_code == 200
        visitor = c.post("/api/visitors", json={"display_name": "Synthetic Reusable Guest"}, headers=h)
        assert visitor.status_code == 201
        visitor_id = visitor.json()["id"]
        assert c.get("/api/visitors?q=Reusable").json() == [visitor.json()]
        # Reuse the selected stable identity; do not merge different people by name.
        for _ in range(2):
            body = order_body(g, employee_number=None, visitor_id=visitor_id,
                              allocations=[{"category": "finance", "amount": "245.00"}])
            created = c.post("/api/orders", json=body, headers=h)
            assert created.status_code == 201, created.text
            # Both roles can mark a visitor order Received even if its old allocation is incomplete.
            edited = c.patch(f'/api/orders/{created.json()["order_id"]}', json={"expected_version": 1,
                "allocations": [{"category": "finance", "amount": "240.00"}]}, headers=h)
            assert edited.status_code == 200 and edited.json()["version"] == 2
            assert c.post(f'/api/orders/{created.json()["order_id"]}/received',
                          json={"expected_version": 2}, headers=h).status_code == 200
            assert c.get(f'/api/orders/{created.json()["order_id"]}').json()['allocations'][0]['amount'] == '245.00'
        assert len(c.get("/api/visitors?q=Reusable").json()) == 1
        dish = c.post("/api/dishes", json={"name": "Synthetic Lunch", "category_code": "vegetable"}, headers=h)
        assert dish.status_code == 201 and dish.json()["is_active"] is True
        assert c.get("/api/dishes?q=Lunch&category=vegetable&active=true").json() == [dish.json()]
        menu = c.post("/api/menus", json={"dish_ids": [dish.json()["id"]], "assignments": [
            {"service_date": "2040-01-04", "expected_menu_id": None},
            {"service_date": "2040-01-05", "expected_menu_id": None}]}, headers=h)
        assert menu.status_code == 201, menu.text
        for day in ("2040-01-04", "2040-01-05"):
            dated = c.get(f"/api/menus/by-date/{day}").json()
            assert dated["id"] == menu.json()["id"]
            assert dated["items"][0]["unit_price"] == "50.00"
        reports = c.get("/api/reports/bundle?mode=daily&day=2040-01-02")
        assert reports.status_code == 200, reports.text
        assert reports.json()["sales"]["recognized_sales"] == "490.00"
        assert reports.json()["salary_deduction"]["total"] == "0.00"
    with engine.connect() as connection:
        event_row = sql(connection, "SELECT actor_user_id,after_values FROM audit_events WHERE action='visitor_created'").one()
        assert event_row.actor_user_id == g["actor"] and event_row.after_values["id"] == visitor_id


def test_csv_import_search_privacy_reimport_and_role_denial(auth_env, caplog):
    engine, g, _, _, password, _, runtime = auth_env
    data = csv_bytes([person("0001", "Synthetic Alpha", email_address="synthetic-private@example.invalid"),
                      person("1", "Synthetic Beta")])
    with client(runtime) as c:
        h = headers(login_http(c, password).json()["csrf_token"]) | {"Content-Type": "text/csv"}
        imported = c.post("/api/employees/import", content=data, headers=h)
        assert imported.status_code == 200, imported.text
        assert imported.json()["inserted_rows"] == 2 and imported.json()["errors"] == []
        repeated = c.post("/api/employees/import", content=data, headers=h)
        assert repeated.json()["unchanged_rows"] == 2
        found = c.get("/api/employees?q=0001").json()
        assert found == [{"employee_number": "0001", "full_name": "Synthetic Alpha", "position": None,
                          "campaign": None, "line_of_business": None}]
        assert c.get("/api/employees?q=Alpha").json() == found
        zero_order = c.post("/api/orders", json=order_body(g, employee_number="0001"),
                            headers={key: value for key, value in h.items() if key != "Content-Type"})
        assert zero_order.status_code == 201
        assert c.get(f'/api/orders/{zero_order.json()["order_id"]}').json()["employee_number"] == "0001"
        assert c.get("/api/employees?q=%25").json() == []
        assert len(c.get("/api/employees?limit=1").json()) == 1
        assert c.get("/api/employees?limit=1&offset=1").json() != c.get("/api/employees?limit=1").json()
        assert c.get("/api/employees?offset=10000").json() == []
        bad = c.post("/api/employees/import", content=csv_bytes([person("SYN-DUP"), person("SYN-DUP")]), headers=h)
        assert bad.status_code == 422 and bad.json()["rejected_rows"] == 2
        assert bad.json()["errors"][0]["issues"] == [{"field": "employee_number", "code": "DUPLICATE_EMPLOYEE_NUMBER"}]
        assert "SYN-DUP" not in bad.text
        assert "synthetic-private" not in imported.text + caplog.text
        with engine.begin() as connection:
            sql(connection, "UPDATE users SET role_code='assistant_admin' WHERE id=:id", id=g["actor"])
            jobs = sql(connection, "SELECT count(*) FROM employee_imports").scalar_one()
        assert c.post("/api/employees/import", content=data, headers=h).status_code == 403
        with engine.connect() as connection:
            assert sql(connection, "SELECT count(*) FROM employee_imports").scalar_one() == jobs


@pytest.mark.parametrize("content_type,data,status,code", [
    ("application/json", b"{}", 415, None), ("application/octet-stream", b"PKsynthetic", 415, None),
    ("text/csv", b"\xff", 422, "INVALID_ENCODING"),
    ("text/csv", b"unsupported,headers\n", 422, "INVALID_HEADERS"),
    ("text/csv", b"x" * (8 * 1024 * 1024 + 1), 413, None),
], ids=["json-rejected", "binary-rejected", "invalid-encoding", "invalid-headers", "oversized"])
def test_import_upload_limits_and_file_errors(auth_env, content_type, data, status, code):
    _, _, _, _, password, _, runtime = auth_env
    with client(runtime) as c:
        h = headers(login_http(c, password).json()["csrf_token"]) | {"Content-Type": content_type}
        response = c.post("/api/employees/import", content=data, headers=h)
        assert response.status_code == status, response.text
        if code:
            assert response.json()["file_error_code"] == code


def test_orders_split_edits_transitions_conflicts_and_current_reports(auth_env):
    engine, g, _, _, password, _, runtime = auth_env
    with client(runtime) as c:
        logged = login_http(c, password).json()
        h = headers(logged["csrf_token"])
        h["X-User-Id"] = "9223372036854775807"  # Cannot replace the cookie's audit identity.
        body = order_body(g)
        created = c.post("/api/orders", json=body, headers=h)
        assert created.status_code == 201 and created.json()["total"] == "245.00"
        order_id = created.json()["order_id"]
        base = f"/api/orders/{order_id}"
        assert c.post("/api/orders", json=body, headers=h).json() == created.json()
        assert c.get("/api/reports/sales?mode=daily&day=2040-01-02").json()["recognized_sales"] == "0.00"
        detail = c.get(base).json()
        edited = c.patch(base, json={"expected_version": 1,
            "quantities": [{"line_id": detail["items"][0]["id"], "quantity": 2}],
            "allocations": [{"category": "cash", "amount": "250.00"}, {"category": "sd", "amount": "45.00"}]}, headers=h)
        assert edited.status_code == 200 and edited.json()["version"] == 2 and edited.json()["total"] == "295.00"
        assert c.patch(base, json={"expected_version": 1}, headers=h).status_code == 409
        marked = c.post(base + "/received", json={"expected_version": 2}, headers=h)
        assert marked.status_code == 200 and marked.json()["version"] == 3
        assert c.patch(base, json={"expected_version": 3}, headers=h).status_code == 409
        listed = c.get("/api/orders", params={"status": "received", "employee_number": g["employee"],
                        "start": "2040-01-02", "end": "2040-01-02"}).json()
        assert len(listed) == 1 and listed[0]["total"] == "295.00"
        for query in ("mode=daily&day=2040-01-02", "mode=weekly&day=2040-01-02",
                      "mode=monthly&year=2040&month=1", "mode=custom&start=2040-01-01&end=2040-01-03"):
            bundle = c.get("/api/reports/bundle?" + query).json()
            assert bundle["sales"]["recognized_sales"] == "295.00"
            assert bundle["payments"]["total"] == "295.00" and bundle["salary_deduction"]["total"] == "45.00"
            assert bundle["salary_deduction"]["orders"][0]["employee_number"] == g["employee"]
        assert c.get("/api/reports/payments?mode=daily&day=2040-01-02").json()["total"] == "295.00"
        assert c.get("/api/reports/salary-deduction?mode=daily&day=2040-01-02").json()["total"] == "45.00"
        correction = {"expected_version": 3, "reason_code": "other", "acknowledged": True, "explanation": "Synthetic correction"}
        for bad in ({"acknowledged": False}, {"explanation": "   "}, {"acknowledged": "true"}, {"actor_id": g["actor"]}):
            assert c.post(base + "/reverse-received", json=correction | bad, headers=h).status_code == 422
        with engine.begin() as connection:
            sql(connection, "UPDATE users SET role_code='assistant_admin' WHERE id=:id", id=g["actor"])
        assert c.post(base + "/reverse-received", json=correction, headers=h).status_code == 403
        with engine.begin() as connection:
            sql(connection, "UPDATE users SET role_code='admin' WHERE id=:id", id=g["actor"])
        reversed_order = c.post(base + "/reverse-received", json=correction, headers=h)
        assert reversed_order.status_code == 200 and reversed_order.json()["version"] == 4
        assert c.get("/api/reports/bundle?mode=daily&day=2040-01-02").json()["salary_deduction"]["total"] == "0.00"
        assert c.post(base + "/received", json={"expected_version": 3}, headers=h).status_code == 409
        assert c.post(base + "/received", json={"expected_version": 4}, headers=h).json()["version"] == 5
        assert c.get("/api/reports/sales?mode=daily&day=2040-01-02").json()["recognized_sales"] == "295.00"
    with engine.connect() as connection:
        saved = state(connection, order_id)
        assert len(saved["receipts"]) == 3
        assert all(e["actor_user_id"] == g["actor"] for e in saved["audits"])


def test_menu_prices_date_conflicts_and_historical_order_provenance(auth_env):
    engine, g, _, _, password, _, runtime = auth_env
    with client(runtime) as c:
        h = headers(login_http(c, password).json()["csrf_token"])
        created = c.post("/api/orders", json=order_body(g), headers=h).json()
        base = f'/api/orders/{created["order_id"]}'
        original = c.get(base).json()
        with engine.begin() as connection:
            sql(connection, "UPDATE item_categories SET default_unit_price=60 WHERE code='vegetable'")
        menu = c.post("/api/menus", json={"label": "Synthetic New Configuration", "dish_ids": g["dishes"]}, headers=h)
        assert menu.status_code == 201 and menu.json()["items"][0]["unit_price"] == "60.00"
        menu_id = menu.json()["id"]
        schedule = {"assignments": [{"service_date": "2040-01-02", "expected_menu_id": g["menu"]},
                                    {"service_date": "2040-01-03", "expected_menu_id": None}]}
        assert c.put(f"/api/menus/{menu_id}/dates", json=schedule, headers=h).status_code == 200
        assert c.put(f'/api/menus/{g["other"]}/dates', json=schedule, headers=h).status_code == 409
        assert c.get("/api/menus/by-date/2040-01-02").json()["id"] == menu_id
        assert c.get(base).json() == original
        # A change to one assigned date does not silently change the other date.
        assert c.put(f'/api/menus/{g["menu"]}/dates', json={"assignments": [
            {"service_date": "2040-01-03", "expected_menu_id": menu_id}]}, headers=h).status_code == 200
        assert c.get("/api/menus/by-date/2040-01-02").json()["id"] == menu_id
        assert c.get("/api/menus/by-date/2040-01-03").json()["id"] == g["menu"]
        edited = c.patch(base, json={"expected_version": 1,
            "add_items": [{"menu_item_id": g["offerings"][0], "quantity": 1}]}, headers=h)
        assert edited.status_code == 200 and edited.json()["total"] == "295.00"
        updated = c.get(base).json()
        assert updated["menu_id"] == g["menu"] and updated["items"][-1]["unit_price"] == "50.00"
        wrong = c.patch(base, json={"expected_version": 2,
            "add_items": [{"menu_item_id": menu.json()["items"][0]["id"], "quantity": 1}]}, headers=h)
        assert wrong.status_code == 422 and c.get(base).json() == updated


@pytest.mark.parametrize("url", ["/api/employees?limit=101", "/api/visitors?offset=-1", "/api/dishes?category=other",
    "/api/employees?q=" + "x" * 101, "/api/orders?status=paid", "/api/orders/0", "/api/orders?visitor_id=-1",
    "/api/orders?start=2040-01-03&end=2040-01-02", "/api/reports/sales?mode=daily",
    "/api/reports/payments?mode=monthly&year=2040&month=13", "/api/reports/salary-deduction?mode=weekly&day=invalid",
    "/api/reports/bundle?mode=custom&start=2040-01-03&end=2040-01-02",
    "/api/reports/sales?mode=daily&day=2040-01-02&start=2040-01-01"])
def test_invalid_queries_and_safe_errors(auth_env, url):
    _, _, _, _, password, _, runtime = auth_env
    with client(runtime) as c:
        login_http(c, password)
        response = c.get(url)
        assert response.status_code == 422
        assert '"input"' not in response.text and "Traceback" not in response.text


def test_forbidden_input_fields_not_found_and_disabled_account(auth_env):
    engine, g, _, service, password, _, runtime = auth_env
    with client(runtime) as c:
        h = headers(login_http(c, password).json()["csrf_token"])
        for change in ({"actor_id": g["actor"]}, {"role": "admin"}, {"is_received": True},
                       {"customer_name_snapshot": "Synthetic secret"},
                       {"items": [{"menu_item_id": g["offerings"][0], "quantity": 1, "unit_price": "1.00"}]},
                       {"allocations": [{"category": "cash", "amount": 245.00}]}):
            response = c.post("/api/orders", json=order_body(g, **change), headers=h)
            assert response.status_code == 422 and "Synthetic secret" not in response.text
        assert c.post("/api/visitors", json={"display_name": "Synthetic Guest", "email": "synthetic-private"}, headers=h).status_code == 422
        assert c.post("/api/dishes", json={"name": "Synthetic Dish", "category_code": "vegetable", "price": "1"}, headers=h).status_code == 422
        assert c.get("/api/orders/9223372036854775807").status_code == 404
        assert c.get("/api/menus/by-date/2041-01-01").status_code == 404
        with engine.begin() as connection:
            sql(connection, "UPDATE users SET is_enabled=false WHERE id=:id", id=g["actor"])
        for method, url, body in requests(g):
            response = c.request(method, url, json=body, headers=h)
            assert response.status_code == 401, (method, url, response.text)
        with pytest.raises(Forbidden):
            BusinessService(service.session_factory).create_visitor(ActorContext(g["actor"]), "Synthetic Denied")


def test_catalog_audit_failure_and_multidate_conflict_roll_back(auth_env):
    engine, g, _, _, password, _, runtime = auth_env
    def fail_audit(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO audit_events"):
            raise OperationalError("synthetic storage detail", None, None)
    with client(runtime) as c:
        h = headers(login_http(c, password).json()["csrf_token"])
        # Authentication refresh uses no audit. Fail the business audit insertion.
        event.listen(engine, "before_cursor_execute", fail_audit)
        try:
            response = c.post("/api/visitors", json={"display_name": "Synthetic Rolled Back"}, headers=h)
            assert response.status_code == 503 and "synthetic storage detail" not in response.text
        finally:
            event.remove(engine, "before_cursor_execute", fail_audit)
        assert c.get("/api/visitors?q=Rolled").json() == []
        with engine.connect() as connection:
            count = sql(connection, "SELECT count(*) FROM menus").scalar_one()
        response = c.post("/api/menus", json={"dish_ids": g["dishes"], "assignments": [
            {"service_date": "2040-01-03", "expected_menu_id": None},
            {"service_date": "2040-01-02", "expected_menu_id": None}]}, headers=h)
        assert response.status_code == 409
        assert c.get("/api/menus/by-date/2040-01-03").status_code == 404
        with engine.connect() as connection:
            assert sql(connection, "SELECT count(*) FROM menus").scalar_one() == count
