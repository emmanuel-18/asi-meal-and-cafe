"""Opt-in real Next.js proxy + FastAPI integration, synthetic disposable DB only.

Uses the local Node runtime (ASI_TEST_NODE can select an isolated executable).
No credentials, DSNs or employee records are written to fixture files.
"""

import os
import json
from decimal import Decimal
from datetime import timedelta
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from uuid import uuid4

import httpx
import pytest
import uvicorn

from asi_meal_api.auth_http import AuthRuntime, AuthSettings, LoginLimiter
from asi_meal_api.main import create_app
from test_auth import auth_env, passwords
from test_database import sql
from test_orders import concurrent_env


@pytest.mark.skipif(os.environ.get("ASI_WEB_INTEGRATION") != "true", reason="Opt in with ASI_WEB_INTEGRATION=true and --postgres")
def test_real_next_proxy_session_orders_and_csrf(auth_env):
    engine, g, _, auth, password, clock, _ = auth_env
    web = Path(__file__).resolve().parents[2] / "web"
    node = os.environ.get("ASI_TEST_NODE") or shutil.which("node")
    assert node and (web / "node_modules/next/dist/bin/next").is_file(), "Install the existing frontend dependencies first"
    api_socket = socket.socket()
    api_socket.bind(("127.0.0.1", 0))
    api_port = api_socket.getsockname()[1]
    with socket.socket() as allocation:
        allocation.bind(("127.0.0.1", 0))
        web_port = allocation.getsockname()[1]
    origin = f"http://127.0.0.1:{web_port}"
    runtime = AuthRuntime(auth, AuthSettings(frozenset({origin}), "development"), LoginLimiter())
    server = uvicorn.Server(uvicorn.Config(create_app(runtime), log_level="critical", access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[api_socket]), daemon=True)
    process = None
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline, "Disposable API did not start"
            time.sleep(.05)
        process = subprocess.Popen([node, str(web / "node_modules/next/dist/bin/next"), "dev", "--hostname", "127.0.0.1", "--port", str(web_port)],
            cwd=web, env={**os.environ, "ASI_API_ORIGIN": f"http://127.0.0.1:{api_port}", "NEXT_TELEMETRY_DISABLED": "1"},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        with httpx.Client(base_url=origin, timeout=30) as client:
            deadline = time.monotonic() + 60
            while True:
                assert process.poll() is None, "Disposable frontend stopped unexpectedly"
                try:
                    root = client.get("/")
                    if root.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert time.monotonic() < deadline, "Disposable frontend did not start"
                time.sleep(.1)
            assert "ASI Meal Management" in root.text and g["employee"] not in root.text
            assert client.get("/auth/me").status_code == 401
            assert client.get("/api/employees").status_code == 401
            logged = client.post("/auth/login", json={"login_name": "Synthetic.Login", "password": password},
                                 headers={"Origin": origin, "X-ASI-Request": "1"})
            assert logged.status_code == 200
            cookie = logged.headers["set-cookie"].lower()
            assert "asi_dev_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
            assert "domain=" not in cookie
            csrf = logged.json()["csrf_token"]
            h = {"Origin": origin, "X-CSRF-Token": csrf}
            assert client.get("/auth/me").json()["user"]["id"] == g["actor"]
            assert client.get("/api/employees", params={"q": g["employee"]}).json()[0]["employee_number"] == g["employee"]
            # Synthetic raw CSV travels through the real Next rewrite and session boundary.
            csv_header = b"employee_number,full_name,position,campaign,line_of_business,assigned_site,email_address,primary_contact_number,alternative_contact_number,alternative_contact_number_2\n"
            csv_data = csv_header + b"000042,Synthetic Directory Person,Analyst,Example,Operations,,,,,\n"
            csv_headers = h | {"Content-Type": "text/csv"}
            assert client.post("/api/employees/import", content=csv_data, headers={"Origin": origin, "Content-Type": "text/csv"}).status_code == 403
            imported = client.post("/api/employees/import", content=csv_data, headers=csv_headers)
            assert imported.status_code == 200 and imported.json()["inserted_rows"] == 1
            assert client.get("/api/employees", params={"q": "000042", "limit": 1, "offset": 0}).json()[0]["employee_number"] == "000042"
            invalid = csv_header + b"000043,,Analyst,Example,Operations,,,,,\n"
            rejected = client.post("/api/employees/import", content=invalid, headers=csv_headers)
            assert rejected.status_code == 422 and rejected.json()["rejected_rows"] == 1
            assert client.get("/api/employees", params={"q": "000043"}).json() == []
            # Full synthetic example on an otherwise unused service date.
            dishes = []
            for name, category in (("Synthetic Vegetable", "vegetable"), ("Synthetic Main", "non_vegetable"), ("Synthetic Rice", "extra_rice")):
                response = client.post("/api/dishes", headers=h, json={"name": name, "category_code": category})
                assert response.status_code == 201
                dishes.append(response.json()["id"])
            menu_response = client.post("/api/menus", headers=h, json={"label": "Synthetic Operational Demo", "dish_ids": dishes})
            assert menu_response.status_code == 201
            demo_menu = menu_response.json()
            assert [item["unit_price"] for item in demo_menu["items"]] == ["50.00", "75.00", "15.00"]
            demo_day = "2044-01-05"
            assert client.put(f'/api/menus/{demo_menu["id"]}/dates', headers=h, json={"assignments": [{"service_date": demo_day, "expected_menu_id": None}]}).status_code == 200
            common = {"service_date": demo_day, "menu_id": demo_menu["id"], "employee_number": "000042"}
            example = client.post("/api/orders", headers=h, json={**common, "request_key": str(uuid4()),
                "items": [{"menu_item_id": item["id"], "quantity": quantity} for item, quantity in zip(demo_menu["items"], (1, 2, 3))],
                "allocations": [{"category": "cash", "amount": "45.00"}, {"category": "gcash", "amount": "200.00"}]})
            assert example.status_code == 201 and example.json()["total"] == "245.00"
            example_id = example.json()["order_id"]
            saved_example = client.get(f"/api/orders/{example_id}").json()
            assert [line["quantity"] for line in saved_example["items"]] == [1, 2, 3]
            sd_order = client.post("/api/orders", headers=h, json={**common, "request_key": str(uuid4()),
                "items": [{"menu_item_id": demo_menu["items"][0]["id"], "quantity": 1}],
                "allocations": [{"category": "cash", "amount": "20.00"}, {"category": "sd", "amount": "30.00"}]})
            assert sd_order.status_code == 201
            sd_id = sd_order.json()["order_id"]
            params = {"mode": "daily", "day": demo_day}
            assert Decimal(client.get("/api/reports/bundle", params=params).json()["sales"]["recognized_sales"]) == 0
            assert client.post(f"/api/orders/{example_id}/received", headers=h, json={"expected_version": 1}).status_code == 200
            assert client.post(f"/api/orders/{sd_id}/received", headers=h, json={"expected_version": 1}).status_code == 200
            bundle = client.get("/api/reports/bundle", params=params).json()
            assert Decimal(bundle["sales"]["recognized_sales"]) == Decimal("295")
            assert bundle["sales"]["received_order_count"] == 2 and bundle["sales"]["item_quantity"] == 7
            amounts = {row["category"]: Decimal(row["amount"]) for row in bundle["payments"]["totals"]}
            assert amounts["cash"] == 65 and amounts["gcash"] == 200 and amounts["sd"] == 30
            assert Decimal(bundle["salary_deduction"]["total"]) == 30
            assert bundle["salary_deduction"]["orders"][0]["order_id"] == sd_id
            correction = {"expected_version": 2, "reason_code": "mistaken_click", "acknowledged": True}
            assert client.post(f"/api/orders/{sd_id}/reverse-received", headers=h, json=correction).status_code == 200
            reversed_bundle = client.get("/api/reports/bundle", params=params).json()
            assert Decimal(reversed_bundle["sales"]["recognized_sales"]) == 245 and Decimal(reversed_bundle["salary_deduction"]["total"]) == 0
            assert client.post(f"/api/orders/{sd_id}/received", headers=h, json={"expected_version": 3}).status_code == 200
            assert client.get("/api/reports/bundle", params=params).json() == bundle
            with engine.connect() as connection:
                assert sql(connection, "SELECT count(*) FROM receipt_events WHERE order_id=:id", id=sd_id).scalar_one() == 3
                assert sql(connection, "SELECT count(*) FROM receipt_events r JOIN audit_events a ON a.id=r.audit_event_id WHERE r.order_id=:id AND a.actor_user_id=:actor", id=sd_id, actor=g["actor"]).scalar_one() == 3
            assert client.get("/api/menus/9223372036854775807").status_code == 404
            for role in ("admin", "assistant_admin"):
                with engine.begin() as connection:
                    sql(connection, "UPDATE users SET role_code=:role WHERE id=:id", role=role, id=g["actor"])
                    sql(connection, "UPDATE menu_items SET unit_price=50 WHERE id=:id", id=g["offerings"][0])
                assert client.get("/auth/me").json()["user"]["role"] == role
                original = client.post("/api/orders", headers=h, json={"request_key": str(uuid4()), "service_date": str(g["day"]),
                    "menu_id": g["menu"], "employee_number": g["employee"], "items": [
                    {"menu_item_id": g["offerings"][0], "quantity": 1}, {"menu_item_id": g["offerings"][1], "quantity": 2}], "allocations": []})
                assert original.status_code == 201
                edit_id = original.json()["order_id"]
                saved = client.get(f"/api/orders/{edit_id}").json()
                # Date reassignment cannot replace the order's recorded source menu.
                assert client.put(f'/api/menus/{g["other"]}/dates', headers=h, json={"assignments": [
                    {"service_date": str(g["day"]), "expected_menu_id": g["menu"]}]}).status_code == 200
                assert client.get(f'/api/menus/by-date/{g["day"]}').json()["id"] == g["other"]
                recorded = client.get(f'/api/menus/{saved["menu_id"]}')
                assert recorded.status_code == 200 and len(recorded.json()["items"]) == 3
                with engine.begin() as connection:
                    # Synthetic source change: only explicitly added lines use it.
                    sql(connection, "UPDATE menu_items SET unit_price=60 WHERE id=:id", id=g["offerings"][0])
                patch = {"expected_version": saved["version"], "quantities": [{"line_id": saved["items"][0]["id"], "quantity": 2}],
                    "remove_line_ids": [saved["items"][1]["id"]], "add_items": [
                    {"menu_item_id": g["offerings"][2], "quantity": 1}, {"menu_item_id": g["offerings"][0], "quantity": 1}],
                    "allocations": [{"category": "sd", "amount": "100.00"}, {"category": "gcash", "amount": "75.00"}]}
                assert client.patch(f"/api/orders/{edit_id}", json=patch, headers={"Origin": origin}).status_code == 403
                edited = client.patch(f"/api/orders/{edit_id}", json=patch, headers=h)
                assert edited.status_code == 200 and edited.json()["version"] == 2 and edited.json()["total"] == "175.00"
                fresh = client.get(f"/api/orders/{edit_id}").json()
                assert fresh["menu_id"] == saved["menu_id"] and fresh["employee_number"] == saved["employee_number"]
                assert [item["unit_price"] for item in fresh["items"]] == ["50.00", "15.00", "60.00"]
                assert fresh["items"][0]["id"] == saved["items"][0]["id"]
                assert len(client.get("/api/orders", params={"status": "pending", "employee_number": g["employee"]}).json()) == 1
                assert client.patch(f"/api/orders/{edit_id}", json=patch, headers=h).status_code == 409
                assert client.get(f"/api/orders/{edit_id}").json() == fresh
                assert client.patch(f"/api/orders/{edit_id}", json={"expected_version": 2, "employee_number": "forged"}, headers=h).status_code == 422
                params = {"mode": "daily", "day": str(g["day"])}
                before = client.get("/api/reports/bundle", params=params)
                assert before.status_code == 200
                baseline = before.json()
                assert client.post(f"/api/orders/{edit_id}/received", json={"expected_version": 2}, headers=h).status_code == 200
                report = client.get("/api/reports/bundle", params=params).json()
                assert report["sales"]["received_order_count"] == baseline["sales"]["received_order_count"] + 1
                assert Decimal(report["sales"]["recognized_sales"]) - Decimal(baseline["sales"]["recognized_sales"]) == Decimal("175")
                current = {item["category"]: Decimal(item["amount"]) for item in report["payments"]["totals"]}
                prior = {item["category"]: Decimal(item["amount"]) for item in baseline["payments"]["totals"]}
                assert current["sd"] - prior["sd"] == Decimal("100") and current["gcash"] - prior["gcash"] == Decimal("75")
                assert Decimal(report["salary_deduction"]["total"]) - Decimal(baseline["salary_deduction"]["total"]) == Decimal("100")
                snapshot = next(row for row in report["salary_deduction"]["orders"] if row["order_id"] == edit_id)
                assert snapshot["employee_number"] == g["employee"] and snapshot["customer_name"] == fresh["customer_name"]
                if role == "admin":
                    assert client.post(f"/api/orders/{edit_id}/reverse-received", headers=h, json={"expected_version": 3, "reason_code": "mistaken_click", "acknowledged": True}).status_code == 200
                    assert client.get("/api/reports/bundle", params=params).json() == baseline
                    assert client.post(f"/api/orders/{edit_id}/received", headers=h, json={"expected_version": 4}).status_code == 200
                    assert client.get("/api/reports/bundle", params=params).json() == report
                assert client.patch(f"/api/orders/{edit_id}", json={"expected_version": 3, "allocations": []}, headers=h).status_code == 409
                assert client.patch(f"/api/orders/{edit_id}", json={"expected_version": 2, "allocations": []}, headers=h).status_code == 409
                assert client.get(f"/api/orders/{edit_id}").json()["is_received"] is True
                assert client.put(f'/api/menus/{g["menu"]}/dates', headers=h, json={"assignments": [
                    {"service_date": str(g["day"]), "expected_menu_id": g["other"]}]}).status_code == 200
            with engine.begin() as connection:
                sql(connection, "UPDATE users SET role_code='admin' WHERE id=:id", id=g["actor"])
            assert client.post("/api/visitors", json={"display_name": "Synthetic Proxy Guest"}).status_code == 403
            assert client.post("/api/visitors", json={"display_name": "Synthetic Proxy Guest"}, headers=h | {"Origin": "http://untrusted.invalid"}).status_code == 403
            visitor = client.post("/api/visitors", json={"display_name": "Synthetic Proxy Guest"}, headers=h)
            assert visitor.status_code == 201
            matches = client.get("/api/visitors", params={"q": "Synthetic Proxy Guest"})
            assert matches.status_code == 200 and visitor.json() in matches.json()
            menu = client.get(f'/api/menus/by-date/{g["day"]}').json()
            created = client.post("/api/orders", json={"request_key": str(uuid4()), "service_date": str(g["day"]), "menu_id": menu["id"],
                "visitor_id": visitor.json()["id"], "items": [{"menu_item_id": menu["items"][0]["id"], "quantity": 1}],
                "allocations": [{"category": "finance", "amount": menu["items"][0]["unit_price"]}]}, headers=h)
            assert created.status_code == 201
            order_id = created.json()["order_id"]
            assert client.patch(f"/api/orders/{order_id}", json={"expected_version": 1, "allocations": [
                {"category": "cash", "amount": "1.00"}]}, headers=h).status_code == 422
            assert client.patch(f"/api/orders/{order_id}", json={"expected_version": 1, "allocations": []}, headers=h).json()["version"] == 2
            # Approved visitor workflow fills Finance from recorded item totals.
            received = client.post(f"/api/orders/{order_id}/received", json={"expected_version": 2}, headers=h)
            assert received.status_code == 200 and received.json()["version"] == 3
            fresh = client.get(f"/api/orders/{order_id}").json()
            assert [(a["category"], a["amount"]) for a in fresh["allocations"]] == [
                ("finance", menu["items"][0]["unit_price"])]
            assert client.post(f"/api/orders/{order_id}/received", json={"expected_version": 2}, headers=h).status_code == 409
            with engine.begin() as connection:
                sql(connection, "UPDATE users SET role_code='assistant_admin' WHERE id=:id", id=g["actor"])
            assert client.get("/auth/me").json()["user"]["role"] == "assistant_admin"
            correction = {"expected_version": 3, "reason_code": "mistaken_click", "acknowledged": True}
            assert client.post(f"/api/orders/{order_id}/reverse-received", json=correction, headers=h).status_code == 403
            with engine.begin() as connection:
                sql(connection, "UPDATE users SET role_code='admin' WHERE id=:id", id=g["actor"])
            assert client.post(f"/api/orders/{order_id}/reverse-received", json=correction, headers=h).status_code == 200
            assert client.get(f"/api/orders/{order_id}").json()["is_received"] is False
            # Stage 8: both roles create catalog dishes/new definitions and reuse
            # a menu across dates, without rewriting already recorded orders.
            for index, role in enumerate(("admin", "assistant_admin")):
                with engine.begin() as connection:
                    sql(connection, "UPDATE users SET role_code=:role WHERE id=:id", role=role, id=g["actor"])
                    sql(connection, "UPDATE item_categories SET default_unit_price=55 WHERE code='vegetable'")
                name = f"Synthetic Stage Eight Dish {index}"
                dish_response = client.post("/api/dishes", headers=h, json={"name": name, "category_code": "vegetable"})
                assert dish_response.status_code == 201
                dish_id = dish_response.json()["id"]
                catalog = client.get("/api/dishes", params={"q": name, "category": "vegetable", "active": "true"})
                assert catalog.status_code == 200 and catalog.json() == [dish_response.json()]
                assert client.post("/api/menus", headers=h, json={"dish_ids": [dish_id, dish_id]}).status_code == 422
                menu_response = client.post("/api/menus", headers=h, json={"label": f"Synthetic Stage Eight {index}", "dish_ids": [dish_id]})
                assert menu_response.status_code == 201
                reusable = menu_response.json()
                assert reusable["items"][0]["unit_price"] == "55.00"
                assert client.get(f'/api/menus/{reusable["id"]}').json() == reusable
                days = [f"{2042 + index}-02-03", f"{2042 + index}-02-05", f"{2042 + index}-03-01"]
                for day in days:
                    assert client.get(f"/api/menus/by-date/{day}").status_code == 404
                assignment = {"assignments": [{"service_date": day, "expected_menu_id": None} for day in days]}
                assert client.put(f'/api/menus/{reusable["id"]}/dates', json=assignment).status_code == 403
                assert client.put(f'/api/menus/{reusable["id"]}/dates', headers=h, json=assignment).status_code == 200
                for day in days:
                    assert client.get(f"/api/menus/by-date/{day}").json()["id"] == reusable["id"]
                sale = client.post("/api/orders", headers=h, json={"request_key": str(uuid4()), "service_date": days[0],
                    "menu_id": reusable["id"], "employee_number": g["employee"], "items": [{"menu_item_id": reusable["items"][0]["id"], "quantity": 1}], "allocations": []})
                assert sale.status_code == 201
                sale_id = sale.json()["order_id"]
                history = client.get(f"/api/orders/{sale_id}").json()
                replacement = {"assignments": [{"service_date": days[0], "expected_menu_id": reusable["id"]}]}
                assert client.put(f'/api/menus/{g["menu"]}/dates', headers=h, json=replacement).status_code == 200
                assert client.get(f"/api/menus/by-date/{days[0]}").json()["id"] == g["menu"]
                assert client.get(f"/api/menus/by-date/{days[1]}").json()["id"] == reusable["id"]
                assert client.get(f"/api/menus/by-date/{days[2]}").json()["id"] == reusable["id"]
                assert client.get(f"/api/orders/{sale_id}").json() == history
                assert client.get(f'/api/menus/{reusable["id"]}').json() == reusable
                assert client.put(f'/api/menus/{reusable["id"]}/dates', headers=h, json=replacement).status_code == 409
                assert client.get(f"/api/menus/by-date/{days[0]}").json()["id"] == g["menu"]
            assert client.get("/api/employees", params={"q": "000042"}).status_code == 200
            assert client.post("/api/employees/import", content=csv_data, headers=csv_headers).status_code == 403
            # Stage 15: real HTTP proxy -> PostgreSQL -> complete export bundle
            # -> actual XLSX package, with no fixture JSON written to disk.
            with engine.begin() as connection:
                sql(connection, "UPDATE users SET role_code='admin' WHERE id=:id", id=g["actor"])
                sql(connection, "UPDATE item_categories SET default_unit_price=50.01 WHERE code='vegetable'")
            acceptance_day = "2048-01-06"
            response = client.post("/api/menus", headers=h, json={"dish_ids": g["dishes"][:2],
                "include_default_rice": True, "assignments": [{"service_date": acceptance_day, "expected_menu_id": None}]})
            assert response.status_code == 201
            acceptance_menu = response.json()
            assert [i["category_code"] for i in acceptance_menu["items"]].count("extra_rice") == 1
            payment_amounts = {"cash": "10.01", "gcash": "20.02", "sd": "100.00", "incentive": "40.00", "finance": "70.00"}
            body = {"request_key": str(uuid4()), "service_date": acceptance_day, "menu_id": acceptance_menu["id"],
                "employee_number": "000042", "items": [{"menu_item_id": i["id"], "quantity": 3 if i["category_code"] == "vegetable" else 1}
                    for i in acceptance_menu["items"]],
                "allocations": [{"category": category, "amount": amount} for category, amount in payment_amounts.items()]}
            created = client.post("/api/orders", headers=h, json=body)
            assert created.status_code == 201 and created.json()["total"] == "240.03"
            accepted_id = created.json()["order_id"]
            assert client.post("/api/orders", headers=h, json=body).json() == created.json()
            assert client.post("/api/orders", headers=h, json=body | {"allocations": []}).status_code == 409
            pending = client.post("/api/orders", headers=h, json=body | {"request_key": str(uuid4()), "allocations": []})
            assert pending.status_code == 201
            assert client.post(f'/api/orders/{pending.json()["order_id"]}/received', headers=h, json={"expected_version": 1}).status_code == 422
            assert client.post(f"/api/orders/{accepted_id}/received", headers=h, json={"expected_version": 1}).status_code == 200
            assert client.post(f"/api/orders/{accepted_id}/received", headers=h, json={"expected_version": 1}).status_code == 409
            # A current-version retry is a no-op, not a second receipt event.
            assert client.post(f"/api/orders/{accepted_id}/received", headers=h, json={"expected_version": 2}).json()["version"] == 2
            vegetable = next(i for i in acceptance_menu["items"] if i["category_code"] == "vegetable")
            guest = client.post("/api/orders", headers=h, json={"request_key": str(uuid4()), "service_date": acceptance_day,
                "menu_id": acceptance_menu["id"], "visitor_id": visitor.json()["id"],
                "items": [{"menu_item_id": vegetable["id"], "quantity": 1}], "allocations": []})
            assert guest.status_code == 201
            guest_id = guest.json()["order_id"]
            assert client.post(f"/api/orders/{guest_id}/received", headers=h, json={"expected_version": 1}).status_code == 200
            for query in ({"mode": "daily", "day": acceptance_day}, {"mode": "weekly", "day": acceptance_day},
                          {"mode": "monthly", "year": 2048, "month": 1},
                          {"mode": "custom", "start": acceptance_day, "end": "2048-02-06"}):
                exported = client.get("/api/reports/bundle", params=query | {"include_export_details": "true", "q": "no-match", "limit": 1}).json()
                assert exported["sales"]["recognized_sales"] == exported["payments"]["total"] == "290.04"
                assert exported["sales"]["received_order_count"] == 2
                assert exported["salary_deduction"]["total"] == "100.00"
                assert [e["employee_number"] for e in exported["salary_deduction"]["employees"]] == ["000042"]
                expected = payment_amounts | {"finance": "120.01"}
                assert {a["category"]: a["amount"] for a in exported["payments"]["totals"]} == expected
                assert {o["order_id"] for o in exported["export_details"]["orders"]} == {accepted_id, guest_id}
                verify_export_workbook(node, web, exported, query["mode"])
            for path in ("/api/users", "/api/activity"):
                assert client.get(path).status_code == 403
            with engine.begin() as connection:
                assert sql(connection, "SELECT count(*) FROM receipt_events WHERE order_id=:id", id=accepted_id).scalar_one() == 1
                sql(connection, "UPDATE users SET role_code='super_admin' WHERE id=:id", id=g["actor"])
            activity = client.get("/api/activity", params={"entity": "orders", "reference": str(accepted_id)}).json()["items"]
            assert {a["action"] for a in activity} == {"order_created", "received_marked"}
            assert all(a["actor_id"] == g["actor"] for a in activity)
            assert client.post("/auth/logout", headers=h).status_code == 204
            assert client.get("/auth/me").status_code == 401
            assert client.get("/api/reports/bundle", params={"mode": "daily", "day": demo_day}).status_code == 401
            logged_again = client.post("/auth/login", json={"login_name": "Synthetic.Login", "password": password}, headers={"Origin": origin, "X-ASI-Request": "1"})
            assert logged_again.status_code == 200
            clock[0] += timedelta(minutes=31)
            assert client.get("/api/employees").status_code == 401
    finally:
        if process is not None and process.poll() is None:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            else:
                process.terminate()
            process.wait(timeout=15)
        server.should_exit = True
        thread.join(timeout=15)
        api_socket.close()


def verify_export_workbook(node, web, bundle, mode):
    """Feed only synthetic API reporting data to the existing Excel implementation."""
    script = r"""
import assert from 'node:assert/strict';
import ExcelJS from 'exceljs';
import JSZip from 'jszip';
import { buildPremiumExcel } from './src/lib/premium-excel.ts';
let input = ''; for await (const part of process.stdin) input += part;
const { bundle, mode } = JSON.parse(input);
const bytes = await buildPremiumExcel(bundle, mode);
const book = new ExcelJS.Workbook(); await book.xlsx.load(bytes);
assert.deepEqual(book.worksheets.map(s => s.name), ['Executive Dashboard','Daily Sales','Salary Deduction List','Mode of Payment']);
assert.equal(book.worksheets[0].getCell('A5').result, 290.04);
const sd = book.getWorksheet('Salary Deduction List');
const sdIds = []; sd.eachRow(row => row.eachCell(cell => { if (cell.value === '000042') { assert.equal(cell.type, ExcelJS.ValueType.String); sdIds.push(cell.value); } }));
assert.ok(sdIds.length > 0);
const zip = await JSZip.loadAsync(bytes, { checkCRC32: true });
assert.equal(Object.keys(zip.files).filter(p => /^xl\/charts\/chart\d+\.xml$/.test(p)).length, 4);
for (const sheet of book.worksheets) assert.ok(sheet.pageSetup.printArea);
"""
    result = subprocess.run([node, "--input-type=module", "-e", script], cwd=web,
        input=json.dumps({"bundle": bundle, "mode": mode}), text=True, capture_output=True, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    assert result.returncode == 0, f"Synthetic API-to-workbook verification failed: {result.stderr}"
