"""Disposable-only normal HTTP workflow and denied-privilege probe.

Invoked by validate_runtime.py in a new container sharing only the isolated
restore container's network namespace. Never accepts a live database URL.
"""
import csv
from decimal import Decimal
import io
import json
import os
import re
import secrets
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from asi_meal_api.auth import AuthService
from asi_meal_api.auth_http import AuthRuntime, AuthSettings, LoginLimiter
from asi_meal_api.employee_imports import HEADERS
from asi_meal_api.main import create_app
from runtime_identity import evaluate_identity


def main():
    database = os.environ["ASI_PROBE_DATABASE"]
    if not re.fullmatch(r"restore_[0-9a-f]{32}", database):
        raise RuntimeError("Not an isolated restore database")
    engine = create_engine(URL.create("postgresql+psycopg", username="asi_meal_api",
        password=os.environ["ASI_PROBE_DB_PASSWORD"], host="127.0.0.1", port=5432, database=database),
        hide_parameters=True)
    try:
        with engine.connect() as c:
            identity = c.execute(text("""
                SELECT current_database(), current_user, rolsuper, rolcreatedb,
                       rolcreaterole, rolreplication, rolbypassrls,
                       (SELECT count(*) FROM pg_tables
                        WHERE schemaname='public' AND tableowner=current_user)
                FROM pg_roles WHERE rolname=current_user
            """)).one()
            try:
                evaluate_identity({"database": identity[0], "user": identity[1],
                    "superuser": identity[2], "create_database": identity[3],
                    "create_role": identity[4], "replication": identity[5],
                    "bypass_rls": identity[6], "owned_public_tables": identity[7]},
                    expected_database=database)
            except RuntimeError:
                raise RuntimeError("Unexpected runtime identity or flags") from None
        denied = [
            "CREATE TABLE public.forbidden_probe(id int)",
            "CREATE TEMP TABLE forbidden_probe(id int)",
            "CREATE SCHEMA forbidden_probe",
            "CREATE ROLE forbidden_probe",
            "ALTER TABLE orders DISABLE TRIGGER ALL",
            "DROP TABLE orders",
            "TRUNCATE orders",
            "DELETE FROM employees WHERE false",
            "UPDATE audit_events SET reason=reason WHERE false",
            "DELETE FROM receipt_events WHERE false",
            "UPDATE item_categories SET default_unit_price=default_unit_price WHERE false",
            "UPDATE menu_items SET unit_price=unit_price WHERE false",
            "UPDATE orders SET customer_name_snapshot=customer_name_snapshot WHERE false",
            "UPDATE alembic_version SET version_num=version_num WHERE false",
            "SELECT setval(pg_get_serial_sequence('orders','id'),1)",
            "SET ROLE restore_operator",
            "SELECT pg_read_file('/etc/passwd')",
        ]
        for statement in denied:
            try:
                with engine.begin() as c:
                    c.execute(text(statement))
            except DBAPIError as error:
                if getattr(error.orig, "sqlstate", None) != "42501":
                    raise RuntimeError("Unexpected denial SQLSTATE") from None
            else:
                raise RuntimeError("Forbidden database operation succeeded")
        with engine.begin() as c:
            # Needed by the backup's manifest exporter, with no role elevation.
            c.execute(text("SET TRANSACTION READ ONLY"))
            c.execute(text("SELECT pg_export_snapshot()"))
            c.execute(text("SELECT version_num FROM alembic_version"))
            for table in c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars().all():
                quoted = '"' + table.replace('"', '""') + '"'
                c.execute(text("SELECT count(*) FROM public." + quoted))

        auth = AuthService(sessionmaker(bind=engine))
        runtime = AuthRuntime(auth, AuthSettings(frozenset({"https://testserver"})), LoginLimiter())
        with TestClient(create_app(runtime), base_url="https://testserver") as client:
            def call(method, path, status=200, **kwargs):
                response = client.request(method, path, **kwargs)
                if response.status_code != status:
                    raise RuntimeError(f"HTTP probe failed: {method} {path.split('?')[0]}, status {response.status_code}")
                return response.json() if response.content else None

            session = call("POST", "/auth/login", json={"login_name": os.environ["ASI_PROBE_LOGIN"],
                "password": os.environ["ASI_PROBE_LOGIN_PASSWORD"]},
                headers={"Origin": "https://testserver", "X-ASI-Request": "1"})
            h = {"Origin": "https://testserver", "X-CSRF-Token": session["csrf_token"]}
            call("GET", "/auth/me")
            number = "000-S15-" + uuid4().hex
            def import_employee(name):
                output = io.StringIO(newline="")
                writer = csv.writer(output)
                writer.writerow(HEADERS)
                writer.writerow([number, name, "Synthetic Position", "Synthetic Campaign", "Synthetic LOB", "", "", "", "", ""])
                return call("POST", "/api/employees/import", content=output.getvalue().encode(),
                    headers={**h, "Content-Type": "text/csv"})
            import_employee("Synthetic Privilege Employee")
            found = call("GET", "/api/employees?q=" + number)
            if len(found) != 1 or found[0]["employee_number"] != number:
                raise RuntimeError("Employee identifier not preserved")
            dishes = [call("POST", "/api/dishes", 201, json={"name": "Synthetic Privilege " + code,
                "category_code": code}, headers=h) for code in ("vegetable", "non_vegetable")]
            day = "2099-01-15"
            call("GET", "/api/menus/by-date/" + day, 404)
            menu = call("POST", "/api/menus", 201, json={"dish_ids": [d["id"] for d in dishes],
                "include_default_rice": True, "assignments": [{"service_date": day, "expected_menu_id": None}]}, headers=h)
            call("GET", "/api/menus/by-date/" + day)
            call("PUT", f'/api/menus/{menu["id"]}/dates', json={"assignments": [
                {"service_date": "2099-01-16", "expected_menu_id": None}]}, headers=h)
            if len([i for i in menu["items"] if i["category_code"] == "extra_rice"]) != 1:
                raise RuntimeError("Default rice failed")
            prices = {i["id"]: Decimal(i["unit_price"]) for i in menu["items"]}
            total = sum(prices.values())
            def allocations(amount):
                return [{"category": code, "amount": format(value, ".2f")} for code, value in
                    [("cash", Decimal(10)), ("gcash", Decimal(20)), ("sd", Decimal(30)),
                     ("incentive", Decimal(40)), ("finance", amount - 100)]]
            body = {"request_key": str(uuid4()), "service_date": day, "menu_id": menu["id"],
                "employee_number": number, "items": [{"menu_item_id": i, "quantity": 1} for i in prices],
                "allocations": allocations(total)}
            order = call("POST", "/api/orders", 201, json=body, headers=h)
            if call("POST", "/api/orders", 201, json=body, headers=h) != order:
                raise RuntimeError("Request-key retry duplicated")
            path = f'/api/orders/{order["order_id"]}'
            detail = call("GET", path)
            line = detail["items"][0]
            total += prices[line["source_menu_item_id"]]
            edited = call("PATCH", path, json={"expected_version": order["version"],
                "quantities": [{"line_id": line["id"], "quantity": 2}], "allocations": allocations(total)}, headers=h)
            # Exercise DELETE and INSERT child privileges without changing prices.
            detail = call("GET", path)
            last = detail["items"][-1]
            edited = call("PATCH", path, json={"expected_version": edited["version"],
                "remove_line_ids": [last["id"]], "add_items": [{"menu_item_id": last["source_menu_item_id"],
                "quantity": last["quantity"]}]}, headers=h)
            received = call("POST", path + "/received", json={"expected_version": edited["version"]}, headers=h)
            call("POST", path + "/received", 409, json={"expected_version": edited["version"]}, headers=h)
            reversed_order = call("POST", path + "/reverse-received", json={"expected_version": received["version"],
                "reason_code": "mistaken_click", "acknowledged": True}, headers=h)
            call("POST", path + "/received", json={"expected_version": reversed_order["version"]}, headers=h)
            import_employee("Synthetic Privilege Employee Renamed")
            if call("GET", path)["customer_name"] != "Synthetic Privilege Employee":
                raise RuntimeError("Historical customer snapshot changed")
            visitor = call("POST", "/api/visitors", 201, json={"display_name": "Synthetic Privilege Visitor"}, headers=h)
            call("PATCH", f'/api/visitors/{visitor["id"]}', json={"expected_name": visitor["display_name"],
                "display_name": "Synthetic Privilege Visitor Renamed"}, headers=h)
            offering = menu["items"][0]
            visitor_order = call("POST", "/api/orders", 201, json={"request_key": str(uuid4()),
                "service_date": day, "menu_id": menu["id"], "visitor_id": visitor["id"],
                "items": [{"menu_item_id": offering["id"], "quantity": 1}], "allocations": []}, headers=h)
            vpath = f'/api/orders/{visitor_order["order_id"]}'
            call("POST", vpath + "/received", json={"expected_version": visitor_order["version"]}, headers=h)
            vd = call("GET", vpath)
            if [(a["category"], Decimal(a["amount"])) for a in vd["allocations"]] != [("finance", prices[offering["id"]])]:
                raise RuntimeError("Visitor Finance mismatch")
            bundle = call("GET", "/api/reports/bundle?mode=daily&day=" + day + "&include_export_details=true")
            recognized = total + prices[offering["id"]]
            if (Decimal(bundle["sales"]["recognized_sales"]) != recognized
                    or Decimal(bundle["payments"]["total"]) != recognized
                    or Decimal(bundle["salary_deduction"]["total"]) != 30):
                raise RuntimeError("Financial report reconciliation failed")
            call("GET", "/api/activity?limit=10")
            # Supported unused catalog/visitor DELETEs and session cleanup.
            unused = call("POST", "/api/visitors", 201, json={"display_name": "Synthetic Unused Visitor"}, headers=h)
            call("DELETE", f'/api/visitors/{unused["id"]}', 204, json={"expected_name": unused["display_name"]}, headers=h)
            unused_dish = call("POST", "/api/dishes", 201, json={"name": "Synthetic Unused Dish", "category_code": "vegetable"}, headers=h)
            call("DELETE", f'/api/dishes/{unused_dish["id"]}', 204, json={"expected_name": unused_dish["name"], "expected_category": "vegetable"}, headers=h)
            temp_password = secrets.token_urlsafe(24)
            user = call("POST", "/api/users", 201, json={"login_name": "synthetic-" + uuid4().hex,
                "display_name": "Synthetic Managed User", "role": "assistant_admin", "temporary_password": temp_password}, headers=h)
            with TestClient(create_app(runtime), base_url="https://testserver") as other:
                logged = other.post("/auth/login", json={"login_name": user["login_name"], "password": temp_password},
                    headers={"Origin": "https://testserver", "X-ASI-Request": "1"})
                if logged.status_code != 200 or not logged.json()["user"]["password_change_required"]:
                    raise RuntimeError("First-login requirement failed")
                changed = other.post("/auth/change-password", json={"current_password": temp_password,
                    "new_password": secrets.token_urlsafe(32)}, headers={"Origin": "https://testserver",
                    "X-CSRF-Token": logged.json()["csrf_token"]})
                if changed.status_code != 200 or changed.json()["user"]["password_change_required"]:
                    raise RuntimeError("Password change under runtime role failed")
                updated_user = next(u for u in call("GET", "/api/users?q=" + user["login_name"]) if u["id"] == user["id"])
                call("PATCH", f'/api/users/{user["id"]}', json={"expected_updated_at": updated_user["updated_at"],
                    "display_name": "Synthetic Managed User Updated", "is_enabled": False}, headers=h)
                if other.get("/auth/me").status_code != 401:
                    raise RuntimeError("Disabled synthetic user's session not revoked")
            call("POST", "/auth/logout", 204, headers=h)
            call("GET", "/auth/me", 401)
            auth.cleanup()
        print(json.dumps({"runtime": "asi_meal_api", "superuser": False,
            "denied_privilege_probes": len(denied), "normal_http_workflows": "passed",
            "synthetic_received_sales": format(recognized, ".2f"), "synthetic_sd": "30.00"}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never expose SQL parameters, real restored rows, cookies or passwords.
        print("Isolated runtime probe failed: " + (str(error) if isinstance(error, RuntimeError) else type(error).__name__), file=sys.stderr)
        sys.exit(1)
