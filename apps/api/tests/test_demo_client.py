"""Authenticated demo client tests use only the disposable test database."""
from uuid import uuid4

import pytest
import httpx

from asi_meal_api import demo_client
from test_auth import auth_env, client, passwords  # noqa: F401
from test_orders import concurrent_env  # noqa: F401
from test_database import sql
from test_business_http import order_body


def test_demo_client_authenticated_order_retry_and_audit(auth_env, monkeypatch):
    engine, graph, _, _, password, _, runtime = auth_env
    monkeypatch.setattr(demo_client, "ORIGIN", "https://testserver")
    with engine.begin() as connection:
        sql(connection, "UPDATE users SET login_name='demo_seeder' WHERE id=:id", id=graph["actor"])
    with client(runtime) as http:
        demo = demo_client.DemoClient(http)
        with pytest.raises(demo_client.DemoClientError):
            demo.login("incorrect synthetic password")
        demo.login(password)
        body = order_body(graph, request_key=str(uuid4()))
        first = demo.create_order(body)
        assert demo.create_order(body)["order_id"] == first["order_id"]
        with engine.connect() as connection:
            assert sql(connection, "SELECT count(*) FROM orders WHERE request_key=:key", key=body["request_key"]).scalar_one() == 1
            assert sql(connection, "SELECT actor_user_id FROM audit_events WHERE action='order_created' AND entity_key=:id", id=str(first["order_id"])).scalar_one() == graph["actor"]
        visitor_body = order_body(graph, employee_number=None, visitor_id=graph["visitor"], allocations=[{"category": "cash", "amount": "245.00"}])
        with pytest.raises(demo_client.DemoClientError):
            demo.create_order(visitor_body)
        with pytest.raises(demo_client.DemoClientError):
            demo.request("POST", "/api/users", {})
        for path in ("/api/employees/import", "/api/orders/../users", "//example.com/api/orders"):
            with pytest.raises(demo_client.DemoClientError, match="Unsupported"):
                demo.request("POST", path, {})
        with pytest.raises(demo_client.DemoClientError, match="request key"):
            demo.request("POST", "/api/orders", {})


def test_demo_client_disabled_user_and_stops_on_denial(auth_env, monkeypatch):
    engine, graph, _, _, password, _, runtime = auth_env
    monkeypatch.setattr(demo_client, "ORIGIN", "https://testserver")
    with engine.begin() as connection:
        sql(connection, "UPDATE users SET login_name='demo_seeder', is_enabled=false WHERE id=:id", id=graph["actor"])
    with client(runtime) as http:
        demo = demo_client.DemoClient(http)
        with pytest.raises(demo_client.DemoClientError):
            demo.login(password)
        with engine.begin() as connection:
            sql(connection, "UPDATE users SET is_enabled=true WHERE id=:id", id=graph["actor"])
        demo.login(password)
        with engine.begin() as connection:
            sql(connection, "UPDATE users SET is_enabled=false WHERE id=:id", id=graph["actor"])
        with pytest.raises(demo_client.DemoClientError):
            demo.request("GET", "/api/employees")
        with pytest.raises(demo_client.DemoClientError, match="Authentication required"):
            demo.request("GET", "/api/employees")


@pytest.mark.parametrize("status", [401, 403])
def test_authorization_failure_stops_client(status):
    def handler(request):
        if request.url.path == "/auth/login":
            return httpx.Response(200, json={"user": {"login_name": "demo_seeder", "role": "admin", "password_change_required": False}, "csrf_token": "synthetic"})
        return httpx.Response(status)

    http = httpx.Client(base_url=demo_client.ORIGIN, transport=httpx.MockTransport(handler))
    demo = demo_client.DemoClient(http)
    demo.login("synthetic password")
    with pytest.raises(demo_client.DemoClientError, match="stopped"):
        demo.request("GET", "/api/orders")
    with pytest.raises(demo_client.DemoClientError, match="Authentication required"):
        demo.request("GET", "/api/orders")
    demo.close()
