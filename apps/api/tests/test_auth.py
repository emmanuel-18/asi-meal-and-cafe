"""Real authentication using synthetic credentials and verified disposable PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import threading
import warnings
from uuid import uuid4

from alembic import command
from fastapi import Depends
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker

from asi_meal_api.auth import AuthService, AuthenticationFailed, CSRFRejected, Passwords, ProvisioningRejected, decode_token, require_admin
from asi_meal_api.auth_http import AuthRuntime, AuthSettings, LoginLimiter, admin_actor, authenticated_actor
from asi_meal_api.main import create_app
from asi_meal_api.orders import Forbidden
from conftest import alembic_config
from test_database import graph, reject, sql
from test_orders import concurrent_env, request, state


@pytest.fixture(scope="session")
def passwords():
    return Passwords()


@pytest.fixture
def auth_env(concurrent_env, passwords):
    engine, g, orders, actor = concurrent_env
    factory = sessionmaker(bind=engine)
    clock = [datetime.now(timezone.utc)]
    service = AuthService(factory, passwords=passwords, clock=lambda: clock[0])
    password = secrets.token_urlsafe(24)
    with engine.begin() as c:
        sql(c, "UPDATE users SET login_name='Synthetic.Login',password_hash=:hash WHERE id=:id", hash=passwords.hash(password), id=actor.user_id)
    settings = AuthSettings(frozenset({"https://testserver"}))
    runtime = AuthRuntime(service, settings, LoginLimiter())
    return engine, g, orders, service, password, clock, runtime


@pytest.fixture
def empty_auth(postgres, passwords):
    schema = f"auth_{uuid4().hex}"
    with postgres.engine.begin() as c:
        c.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = create_engine(postgres.engine.url, hide_parameters=True, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as c:
            assert c.exec_driver_sql("SELECT current_schema()").scalar_one() == schema
            assert inspect(c).get_table_names() == []
            command.upgrade(alembic_config(c), "head")
        yield engine, AuthService(sessionmaker(bind=engine), passwords=passwords)
    finally:
        engine.dispose()
        with postgres.engine.begin() as c:
            c.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')


def client(runtime):
    base = "https://testserver" if runtime.settings.mode == "https" else "http://127.0.0.1"
    return TestClient(create_app(runtime), base_url=base, client=("127.0.0.1", 50000))


def login_http(c, password, name="Synthetic.Login", origin="https://testserver"):
    return c.post("/auth/login", json={"login_name": name, "password": password},
                  headers={"Origin": origin, "X-ASI-Request": "1"})


def test_argon2id_hashing_and_validation(passwords):
    password = secrets.token_urlsafe(24)
    first, second = passwords.hash(password), passwords.hash(password)
    assert first != second and first.startswith("$argon2id$v=19$m=65536,t=3,p=1$")
    assert passwords.verify(first, password)
    assert not passwords.verify(first, secrets.token_urlsafe(24))
    assert not passwords.verify("synthetic-not-an-argon-hash", password)
    assert not passwords.verify("$argon2id$malformed", password)
    assert not passwords.verify(None, password)
    for invalid in ("abc1234", "", " " * 8, "x" * 1025, "é" * 513, "\ud800", None):
        assert not passwords.valid_input(invalid)
        with pytest.raises(ProvisioningRejected, match="at least 8 characters"):
            passwords.hash(invalid)
    for valid in ("abcd1234", "abcdefgh", "12345678", "é" * 512):
        assert passwords.valid_input(valid)
        assert passwords.verify(passwords.hash(valid), valid)
    padded = " " + password + " "
    encoded = passwords.hash(padded)
    assert passwords.verify(encoded, padded) and not passwords.verify(encoded, padded.strip())


def test_cli_never_echoes_unexpected_credential_arguments(capsys):
    from asi_meal_api.auth_cli import main
    value = secrets.token_urlsafe(24)
    with pytest.raises(SystemExit): main(["bootstrap-admin", "--password", value])
    captured = capsys.readouterr()
    assert value not in captured.out + captured.err


@pytest.mark.parametrize("mode", ["https", "development"])
def test_login_me_logout_cookies_and_no_secret_leak(auth_env, mode, caplog):
    engine, g, _, service, password, _, runtime = auth_env
    if mode == "development":
        runtime.settings = AuthSettings(frozenset({"http://127.0.0.1"}), mode)
    origin = next(iter(runtime.settings.origins))
    with client(runtime) as c:
        assert c.get("/auth/me").status_code == 401
        response = login_http(c, password, "  sYnThEtIc.LoGiN  ", origin)
        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == {"user", "csrf_token"}
        assert payload["user"] == {"id": g["actor"], "login_name": "Synthetic.Login", "display_name": "Synthetic Admin", "role": "admin", "password_change_required": False}
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie and "Domain=" not in cookie
        assert "Max-Age=28800" in cookie and ("Secure" in cookie) == (mode == "https")
        token = c.cookies.get(runtime.settings.cookie)
        assert token not in response.text and password not in response.text
        assert AuthService(service._sessions, passwords=service.passwords).current(token).user.id == g["actor"]
        me = c.get("/auth/me?user_id=999999&role=admin")
        assert me.status_code == 200 and me.json() == payload and me.headers["cache-control"] == "no-store"
        with engine.connect() as connection:
            row = sql(connection, "SELECT * FROM auth_sessions").mappings().one()
            assert bytes(row["token_hash"]) == hashlib.sha256(decode_token(token)).digest()
            assert bytes(row["token_hash"]) != decode_token(token)
            assert bytes(row["csrf_token"]) == decode_token(payload["csrf_token"])
            assert bytes(row["token_hash"]).hex() not in response.text
            audits = sql(connection, "SELECT before_values,after_values FROM audit_events").all()
            assert password not in repr(audits) and token not in repr(audits) and payload["csrf_token"] not in repr(audits)
        for csrf in (None, secrets.token_urlsafe(32)):
            headers = {"Origin": origin}
            if csrf: headers["X-CSRF-Token"] = csrf
            assert c.post("/auth/logout", headers=headers).status_code == 403
            assert c.get("/auth/me").status_code == 200
        logout = c.post("/auth/logout", headers={"Origin": origin, "X-CSRF-Token": payload["csrf_token"]})
        assert logout.status_code == 204 and "Max-Age=0" in logout.headers["set-cookie"]
        with pytest.raises(AuthenticationFailed):
            AuthService(service._sessions, passwords=service.passwords).current(token)
        c.cookies.set(runtime.settings.cookie, token)
        assert c.get("/auth/me").status_code == 401
    assert password not in caplog.text and token not in caplog.text and payload["csrf_token"] not in caplog.text


@pytest.mark.parametrize("failure", ["unknown", "wrong", "disabled", "invalid_hash"])
def test_generic_failures(auth_env, failure):
    engine, g, _, _, password, _, runtime = auth_env
    name = "Synthetic.Missing" if failure == "unknown" else "Synthetic.Login"
    if failure in {"disabled", "invalid_hash"}:
        with engine.begin() as connection:
            if failure == "disabled":
                sql(connection, "UPDATE users SET is_enabled=false WHERE id=:id", id=g["actor"])
            else:
                sql(connection, "UPDATE users SET password_hash='synthetic-invalid-hash' WHERE id=:id", id=g["actor"])
    with client(runtime) as c:
        response = login_http(c, secrets.token_urlsafe(24) if failure == "wrong" else password, name)
        assert response.status_code == 401 and response.json() == {"detail": "Authentication failed"}
        assert response.headers["cache-control"] == "no-store" and "set-cookie" not in response.headers
    with engine.connect() as connection:
        assert sql(connection, "SELECT count(*) FROM auth_sessions").scalar_one() == 0


def test_rotation_csrf_pairing_and_rollback(auth_env, monkeypatch):
    engine, _, _, service, password, _, _ = auth_env
    first = service.login("Synthetic.Login", password, secrets.token_urlsafe(32))
    second = service.login("Synthetic.Login", password, first.token)
    assert first.token != second.token and first.csrf_token != second.csrf_token
    with pytest.raises(AuthenticationFailed): service.current(first.token)
    with pytest.raises(CSRFRejected): service.logout(second.token, first.csrf_token)
    assert service.current(second.token).user == second.user
    original = service._audit
    def fail(*args): raise RuntimeError("Synthetic audit failure")
    monkeypatch.setattr(service, "_audit", fail)
    with pytest.raises(RuntimeError): service.login("Synthetic.Login", password, second.token)
    monkeypatch.setattr(service, "_audit", original)
    assert service.current(second.token).user == second.user
    with engine.connect() as c:
        assert sql(c, "SELECT count(*) FROM auth_sessions").scalar_one() == 2


@pytest.mark.parametrize("expiry", ["idle", "absolute"])
def test_expiration_without_resurrection(auth_env, expiry):
    engine, _, _, service, password, clock, _ = auth_env
    logged = service.login("Synthetic.Login", password)
    if expiry == "idle":
        clock[0] += timedelta(minutes=30)
    else:
        clock[0] += timedelta(hours=7, minutes=50)
        with engine.begin() as c:
            sql(c, "UPDATE auth_sessions SET last_seen_at=:time", time=clock[0])
        clock[0] += timedelta(minutes=10)
    with pytest.raises(AuthenticationFailed): service.current(logged.token)
    with engine.connect() as c:
        assert sql(c, "SELECT expires_at FROM auth_sessions").scalar_one() == logged.expires_at


def test_activity_is_monotonic_and_does_not_extend_absolute_expiry(auth_env):
    engine, _, _, service, password, clock, _ = auth_env
    logged = service.login("Synthetic.Login", password)
    clock[0] += timedelta(minutes=10)
    service.current(logged.token)
    last_seen = clock[0]
    clock[0] -= timedelta(minutes=5)
    service.current(logged.token)
    with engine.connect() as c:
        row = sql(c, "SELECT last_seen_at,expires_at FROM auth_sessions").one()
        assert row == (last_seen, logged.expires_at)


@pytest.mark.parametrize("origin", [None, "null", "https://untrusted.invalid", "https://testserver.evil.invalid"])
def test_csrf_login_and_logout_origin_rejection(auth_env, origin):
    _, _, _, service, password, _, runtime = auth_env
    logged = service.login("Synthetic.Login", password)
    with client(runtime) as c:
        headers = {"X-ASI-Request": "1"}
        if origin is not None: headers["Origin"] = origin
        assert c.post("/auth/login", json={"login_name": "Synthetic.Login", "password": password}, headers=headers).status_code == 403
        c.cookies.set(runtime.settings.cookie, logged.token)
        headers["X-CSRF-Token"] = logged.csrf_token
        assert c.post("/auth/logout", headers=headers).status_code == 403
        assert service.current(logged.token).user == logged.user


def test_http_boundaries_and_safe_unavailability(auth_env, monkeypatch):
    _, _, _, _, password, _, runtime = auth_env
    with client(runtime) as c:
        assert c.post("/auth/login", json={"login_name": "Synthetic.Login", "password": password}, headers={"Origin": "https://testserver"}).status_code == 403
        assert c.post("/auth/login", data={"password": password}, headers={"Origin": "https://testserver", "X-ASI-Request": "1"}).status_code == 403
        bad = c.post("/auth/login", json={"login_name": "Synthetic.Login", "password": password, "user_id": 1}, headers={"Origin": "https://testserver", "X-ASI-Request": "1"})
        assert bad.status_code == 400 and password not in bad.text
        assert c.get("/auth/logout").status_code == 405
    monkeypatch.delenv("ASI_AUTH_ENABLED", raising=False)
    with TestClient(create_app(), base_url="https://testserver") as c:
        assert c.get("/health").status_code == 200
        assert c.get("/auth/me").status_code == 503
        from conftest import EXPECTED_HTTP_ROUTES
        paths = c.get("/openapi.json").json()["paths"]
        assert {path: set(operations) for path, operations in paths.items()} == EXPECTED_HTTP_ROUTES
    monkeypatch.setenv("ASI_AUTH_ENABLED", "true")
    monkeypatch.delenv("ASI_AUTH_ORIGINS", raising=False)
    with pytest.raises(RuntimeError, match="Invalid authentication configuration"):
        with TestClient(create_app()): pass


@pytest.mark.parametrize("mode,origin", [("https", "http://localhost"), ("https", "*"),
    ("development", "http://public.invalid"), ("development", "https://localhost"), ("invalid", "https://testserver")])
def test_invalid_security_configuration(mode, origin):
    with pytest.raises(ValueError): AuthSettings(frozenset({origin}), mode)


def test_verified_actor_dependencies_and_stored_role_enforcement(auth_env):
    engine, g, orders, service, password, _, runtime = auth_env
    application = create_app(runtime)
    # Isolated test probes; not part of the application route registry.
    @application.get("/probe/actor")
    def actor_probe(actor=Depends(authenticated_actor)): return {"id": actor.user_id}
    @application.get("/probe/admin")
    def admin_probe(actor=Depends(admin_actor)): return {"id": actor.user_id}
    @application.post("/probe/action")
    def action_probe(actor=Depends(authenticated_actor)): return {"id": actor.user_id}
    with TestClient(application, base_url="https://testserver") as c:
        assert c.get("/probe/actor").status_code == 401
        logged = login_http(c, password)
        assert logged.status_code == 200
        assert c.get("/probe/admin").json() == {"id": g["actor"]}
        assert c.post("/probe/action", headers={"Origin": "https://testserver"}).status_code == 403
        assert c.post("/probe/action", headers={"Origin": "https://testserver", "X-CSRF-Token": logged.json()["csrf_token"]}).json() == {"id": g["actor"]}
        identity = service.current(c.cookies.get(runtime.settings.cookie)).user
        order = orders.create_pending(identity.actor, request(g))
        with engine.begin() as connection:
            sql(connection, "UPDATE users SET role_code='assistant_admin' WHERE id=:id", id=g["actor"])
        assistant = service.current(c.cookies.get(runtime.settings.cookie)).user
        assert assistant.role == "assistant_admin" and c.get("/probe/admin").status_code == 403
        assert c.get("/probe/actor?user_id=9999&role=admin").json() == {"id": g["actor"]}
        marked = orders.mark_received(assistant.actor, order.order_id, order.version)
        from asi_meal_api.orders import Correction
        with pytest.raises(Forbidden): orders.reverse_received(assistant.actor, order.order_id, marked.version, Correction("mistaken_click", True))
        from asi_meal_api.employee_imports import EmployeeImportService
        from asi_meal_api.reports import DateRange, ReportingService
        from test_employee_imports import csv_bytes, person
        with pytest.raises(Forbidden):
            EmployeeImportService(service._sessions).import_csv(assistant.actor, csv_bytes([person()]))
        assert ReportingService(service._sessions).sales_summary(assistant.actor, DateRange.daily(g["day"])).recognized_sales == marked.total
        with engine.begin() as connection:
            sql(connection, "UPDATE users SET role_code='super_admin' WHERE id=:id", id=g["actor"])
        super_admin = service.current(c.cookies.get(runtime.settings.cookie)).user
        assert super_admin.role == "super_admin" and c.get("/probe/admin").status_code == 200
        assert EmployeeImportService(service._sessions).import_csv(super_admin.actor, csv_bytes([person()])).status == "completed"
        reversed_order = orders.reverse_received(super_admin.actor, order.order_id, marked.version, Correction("mistaken_click", True))
        assert not reversed_order.is_received
        assert ReportingService(service._sessions).sales_summary(super_admin.actor, DateRange.daily(g["day"])).recognized_sales == 0
        with engine.begin() as connection:
            sql(connection, "UPDATE users SET is_enabled=false WHERE id=:id", id=g["actor"])
        assert c.get("/probe/actor").status_code == 401


def test_first_admin_and_concurrent_provisioning(empty_auth):
    engine, service = empty_auth
    barrier = threading.Barrier(2)
    def provision():
        barrier.wait(timeout=10)
        try: return service.provision_first_admin("Synthetic." + uuid4().hex, "Synthetic Initial Admin", secrets.token_urlsafe(24))
        except ProvisioningRejected: return "refused"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result(timeout=20) for f in [pool.submit(provision), pool.submit(provision)]]
    assert results.count("refused") == 1
    with engine.begin() as c:
        assert sql(c, "SELECT count(*) FROM users").scalar_one() == 1
        assert sql(c, "SELECT count(*) FROM audit_events WHERE action='first_admin_provisioned'").scalar_one() == 1
        sql(c, "UPDATE users SET is_enabled=false")
    with pytest.raises(ProvisioningRejected): service.provision_first_admin("Another", "Synthetic", secrets.token_urlsafe(24))


def test_provisioning_rollback_and_cli(empty_auth, monkeypatch, capsys):
    engine, service = empty_auth
    with pytest.raises(ProvisioningRejected, match="at least 8 characters"):
        service.provision_first_admin("Synthetic", "Synthetic Admin", "abc1234")
    original = service._audit
    def fail(*args): raise RuntimeError("Synthetic failure")
    monkeypatch.setattr(service, "_audit", fail)
    with pytest.raises(RuntimeError): service.provision_first_admin("Synthetic", "Synthetic Admin", secrets.token_urlsafe(24))
    with engine.connect() as c: assert sql(c, "SELECT count(*) FROM users").scalar_one() == 0
    monkeypatch.setattr(service, "_audit", original)
    from asi_meal_api import auth_cli
    monkeypatch.setenv("ASI_DATABASE_URL", "postgresql+psycopg://synthetic-patched-engine")
    monkeypatch.setattr(auth_cli.sys.stdin, "isatty", lambda: False)
    assert auth_cli.main(["bootstrap-admin"]) == 1
    monkeypatch.setattr(auth_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(auth_cli, "create_engine", lambda *a, **kw: engine)
    monkeypatch.setattr(auth_cli, "AuthService", lambda *a, **kw: service)
    prompts = iter(["Synthetic.Initial", "Synthetic Initial Admin"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(prompts))
    password = "abcd1234"  # Synthetic test credential only.
    monkeypatch.setattr(auth_cli.getpass, "getpass", lambda prompt: password)
    assert auth_cli.main(["bootstrap-admin"]) == 0
    output = capsys.readouterr()
    assert password not in output.out + output.err and "$argon2" not in output.out + output.err
    assert service.login("synthetic.initial", password).user.role == "admin"


def test_cleanup_and_concurrent_logout_do_not_resurrect(auth_env):
    engine, _, _, service, password, clock, _ = auth_env
    logged = service.login("Synthetic.Login", password)
    barrier = threading.Barrier(2)
    def read():
        barrier.wait(timeout=10)
        try: return service.current(logged.token)
        except AuthenticationFailed: return None
    def logout():
        barrier.wait(timeout=10)
        service.logout(logged.token, logged.csrf_token)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(read), pool.submit(logout)]
        for task in tasks: task.result(timeout=15)
    with pytest.raises(AuthenticationFailed): service.current(logged.token)
    second = service.login("Synthetic.Login", password)
    assert service.cleanup(limit=1) == 1
    assert service.current(second.token).user == second.user
    clock[0] += timedelta(hours=8)
    assert service.cleanup() == 1
    with engine.connect() as c:
        assert sql(c, "SELECT count(*) FROM auth_sessions").scalar_one() == 0
        assert sql(c, "SELECT count(*) FROM audit_events").scalar_one() >= 3


def test_login_rehash_and_independent_browser_sessions(auth_env):
    engine, g, _, service, password, _, _ = auth_env
    from argon2 import PasswordHasher, Type
    older = PasswordHasher(memory_cost=19456, time_cost=2, parallelism=1, type=Type.ID).hash(password)
    with engine.begin() as c:
        sql(c, "UPDATE users SET password_hash=:hash WHERE id=:id", hash=older, id=g["actor"])
    first = service.login("Synthetic.Login", password)
    second = service.login("Synthetic.Login", password)  # No previous browser cookie.
    with engine.connect() as c:
        hashed = sql(c, "SELECT password_hash FROM users WHERE id=:id", id=g["actor"]).scalar_one()
        assert hashed != older and not service.passwords.hasher.check_needs_rehash(hashed)
    service.logout(first.token, first.csrf_token)
    assert service.current(second.token).user == second.user


def test_cookie_transport_rate_limit_and_storage_failure(auth_env, monkeypatch):
    _, _, _, service, password, _, runtime = auth_env
    with TestClient(create_app(runtime), base_url="http://testserver") as c:
        assert c.get("/auth/me").status_code == 403
    dev = AuthRuntime(service, AuthSettings(frozenset({"http://127.0.0.1"}), "development"), LoginLimiter())
    with TestClient(create_app(dev), base_url="http://127.0.0.1", client=("192.0.2.1", 50000)) as c:
        assert c.get("/auth/me").status_code == 403
    with client(runtime) as c:
        for _ in range(5):
            assert login_http(c, secrets.token_urlsafe(24)).status_code == 401
        assert login_http(c, password).status_code == 429
    from sqlalchemy.exc import OperationalError
    def unavailable(*args, **kwargs):
        raise OperationalError("PRIVATE_STATEMENT", {}, RuntimeError("PRIVATE_STORAGE_DETAIL"))
    monkeypatch.setattr(service, "current", unavailable)
    with client(runtime) as c:
        response = c.get("/auth/me")
        assert response.status_code == 503 and "PRIVATE" not in response.text
        assert response.headers["cache-control"] == "no-store"


def test_cli_mismatch_and_hidden_terminal_failure(empty_auth, monkeypatch, capsys):
    engine, service = empty_auth
    from asi_meal_api import auth_cli
    monkeypatch.setenv("ASI_DATABASE_URL", "postgresql+psycopg://synthetic-patched-engine")
    monkeypatch.setattr(auth_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(auth_cli, "create_engine", lambda *a, **kw: engine)
    monkeypatch.setattr(auth_cli, "AuthService", lambda *a, **kw: service)
    monkeypatch.setattr("builtins.input", lambda prompt: "Synthetic Admin")
    values = iter([secrets.token_urlsafe(24), secrets.token_urlsafe(24)])
    monkeypatch.setattr(auth_cli.getpass, "getpass", lambda prompt: next(values))
    assert auth_cli.main(["bootstrap-admin"]) == 1
    def no_hidden_input(prompt):
        warnings.warn("Synthetic visible fallback", auth_cli.getpass.GetPassWarning)
        pytest.fail("Visible input fallback must not execute")
    monkeypatch.setattr(auth_cli.getpass, "getpass", no_hidden_input)
    assert auth_cli.main(["bootstrap-admin"]) == 1
    with engine.connect() as c:
        assert sql(c, "SELECT count(*) FROM users").scalar_one() == 0


def test_session_revision_preserves_business_data_and_constraints(empty_auth):
    engine, service = empty_auth
    with engine.begin() as c: g = graph(c)
    from asi_meal_api.orders import OrderService, ActorContext
    orders = OrderService(service._sessions)
    recorded = orders.create_pending(ActorContext(g["actor"]), request(g))
    password = secrets.token_urlsafe(24)
    with engine.begin() as c:
        login_name = sql(c, "SELECT login_name FROM users WHERE id=:id", id=g["actor"]).scalar_one()
        sql(c, "UPDATE users SET password_hash=:hash WHERE id=:id", hash=service.passwords.hash(password), id=g["actor"])
    logged = service.login(login_name, password)
    with engine.begin() as c:
        before = state(c, recorded.order_id)
        command.downgrade(alembic_config(c), "0002_reference_data")
        assert "auth_sessions" not in inspect(c).get_table_names()
        assert state(c, recorded.order_id) == before
        command.upgrade(alembic_config(c), "head")
        assert state(c, recorded.order_id) == before
        for statement in [
            "INSERT INTO auth_sessions (user_id,token_hash,csrf_token,expires_at) VALUES (:id,decode('00','hex'),decode(repeat('00',32),'hex'),now()+interval '1 hour')",
            "INSERT INTO auth_sessions (user_id,token_hash,csrf_token,expires_at) VALUES (:id,decode(repeat('00',32),'hex'),decode(repeat('00',32),'hex'),now())",
            "INSERT INTO auth_sessions (user_id,token_hash,csrf_token,expires_at) VALUES (:id,decode(repeat('00',32),'hex'),decode(repeat('00',32),'hex'),'infinity')",
        ]: reject(c, statement, id=g["actor"])
        sql(c, "INSERT INTO auth_sessions (user_id,token_hash,csrf_token,expires_at) "
            "VALUES (:id,decode(repeat('00',32),'hex'),decode(repeat('00',32),'hex'),now()+interval '1 hour')", id=g["actor"])
        reject(c, "INSERT INTO auth_sessions (user_id,token_hash,csrf_token,expires_at) "
               "VALUES (:id,decode(repeat('00',32),'hex'),decode(repeat('00',32),'hex'),now()+interval '1 hour')", id=g["actor"])
        reject(c, "INSERT INTO auth_sessions (user_id,token_hash,csrf_token,expires_at) "
               "VALUES (99999999,decode(repeat('01',32),'hex'),decode(repeat('01',32),'hex'),now()+interval '1 hour')")
    with pytest.raises(AuthenticationFailed): service.current(logged.token)


def test_user_management_and_required_password_change(auth_env):
    engine, g, _, _, password, _, runtime = auth_env
    with engine.begin() as c:
        sql(c, "UPDATE users SET role_code='super_admin' WHERE id=:id", id=g['actor'])
    origin = {"Origin": "https://testserver"}
    temporary, replacement = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    with client(runtime) as admin, client(runtime) as created:
        login = login_http(admin, password)
        headers = {**origin, "X-CSRF-Token": login.json()["csrf_token"]}
        response = admin.post('/api/users', headers=headers, json={"login_name":"Synthetic.New", "display_name":"Synthetic Person", "role":"assistant_admin", "temporary_password":temporary})
        assert response.status_code == 201, response.text
        account = response.json()
        assert account['password_change_required'] and temporary not in response.text
        assert admin.post('/api/users', headers=headers, json={"login_name":"synthetic.new", "display_name":"Synthetic", "role":"admin", "temporary_password":temporary}).status_code == 409
        login = login_http(created, temporary, name='Synthetic.New')
        assert login.status_code == 200 and login.json()['user']['password_change_required']
        change_headers = {**origin, 'X-CSRF-Token': login.json()['csrf_token']}
        assert created.get('/api/dishes').status_code == 403
        assert created.get('/api/users').status_code == 403
        assert created.post('/auth/change-password', json={'current_password':temporary, 'new_password':replacement}).status_code == 403
        changed = created.post('/auth/change-password', headers=change_headers, json={'current_password':temporary, 'new_password':replacement})
        assert changed.status_code == 200 and not changed.json()['user']['password_change_required']
        assert created.get('/api/dishes').status_code == 200
        assert created.get('/api/users').status_code == 403
        changed_account = admin.patch(f"/api/users/{account['id']}", headers=headers, json={"expected_updated_at": account['updated_at'], "is_enabled": False})
        # Password change updates the account version: stale admin state must conflict.
        assert changed_account.status_code == 409
        account = next(u for u in admin.get('/api/users').json() if u['id'] == account['id'])
        assert admin.patch(f"/api/users/{account['id']}", headers=headers, json={"expected_updated_at": account['updated_at'], "is_enabled": False}).status_code == 200
        assert created.get('/auth/me').status_code == 401
        with engine.connect() as c:
            audits = repr(sql(c, "SELECT before_values,after_values FROM audit_events").all())
            assert temporary not in audits and replacement not in audits


def test_promote_admin1_cli_is_explicit_audited_and_idempotent(auth_env, monkeypatch, capsys):
    from asi_meal_api import auth_cli
    engine, g, _, service, password, _, _ = auth_env
    with engine.begin() as c:
        sql(c, "UPDATE users SET login_name='admin1' WHERE id=:id", id=g['actor'])
    existing = service.login('admin1', password)
    monkeypatch.setenv('ASI_DATABASE_URL', 'postgresql+psycopg://synthetic')
    monkeypatch.setattr(auth_cli, 'create_engine', lambda *args, **kwargs: engine)
    monkeypatch.setattr(engine, 'dispose', lambda: None)
    monkeypatch.setattr(auth_cli.sys.stdin, 'isatty', lambda: True)
    def run_cli():
        entries = iter(['Synthetic operator', 'Synthetic reason', 'PROMOTE admin1'])
        monkeypatch.setattr('builtins.input', lambda prompt: next(entries))
        return auth_cli.main(['promote-admin1'])
    assert run_cli() == 0
    with pytest.raises(AuthenticationFailed):
        service.current(existing.token)
    assert service.login('admin1', password).user.role == 'super_admin'
    assert run_cli() == 0
    with engine.connect() as c:
        rows = sql(c, "SELECT before_values,after_values,reason FROM audit_events WHERE action='super_admin_promoted'").mappings().all()
        assert len(rows) == 1
        assert rows[0]['before_values']['role'] == 'admin'
        assert rows[0]['after_values']['role'] == 'super_admin'
        assert rows[0]['after_values']['attribution'] == 'local_self_attested'
        assert rows[0]['reason'] == 'Synthetic reason'
    assert password not in capsys.readouterr().out


def test_account_management_role_and_session_revocation(auth_env):
    engine, g, _, _, password, _, runtime = auth_env
    with engine.begin() as c:
        sql(c, "UPDATE users SET role_code='super_admin' WHERE id=:id", id=g['actor'])
    origin = {'Origin': 'https://testserver'}
    temporary = secrets.token_urlsafe(24)
    reset = secrets.token_urlsafe(24)
    with client(runtime) as admin, client(runtime) as managed:
        auth = login_http(admin, password).json()
        headers = {**origin, 'X-CSRF-Token': auth['csrf_token']}
        self_row = next(u for u in admin.get('/api/users').json() if u['id'] == g['actor'])
        assert admin.patch(f"/api/users/{g['actor']}", headers=headers, json={'expected_updated_at':self_row['updated_at'], 'is_enabled':False}).status_code == 403
        assert admin.post('/api/users', headers=headers, json={'login_name':'nope', 'display_name':'Synthetic', 'role':'super_admin', 'temporary_password':temporary}).status_code == 422
        account = admin.post('/api/users', headers=headers, json={'login_name':'Synthetic.Admin', 'display_name':'Synthetic', 'role':'admin', 'temporary_password':temporary}).json()
        signed = login_http(managed, temporary, name='Synthetic.Admin').json()
        managed_headers = {**origin, 'X-CSRF-Token':signed['csrf_token']}
        assert managed.get('/api/users').status_code == 403
        assert managed.post('/auth/change-password', headers=managed_headers, json={'current_password':temporary, 'new_password':reset}).status_code == 200
        assert managed.get('/api/users').status_code == 403
        account = next(u for u in admin.get('/api/users').json() if u['id'] == account['id'])
        changed = admin.patch(f"/api/users/{account['id']}", headers=headers, json={'expected_updated_at':account['updated_at'], 'role':'assistant_admin'})
        assert changed.status_code == 200
        assert managed.get('/auth/me').status_code == 401
        account = changed.json()
        updated = admin.patch(f"/api/users/{account['id']}", headers=headers, json={'expected_updated_at':account['updated_at'], 'temporary_password':temporary})
        assert updated.status_code == 200 and updated.json()['password_change_required']
        signed = login_http(managed, temporary, name='Synthetic.Admin').json()
        assert signed['user']['password_change_required']
        assert managed.get('/api/reports/bundle?mode=daily&day=2026-01-01').status_code == 403
        account = updated.json()
        disabled = admin.patch(f"/api/users/{account['id']}", headers=headers, json={'expected_updated_at':account['updated_at'], 'is_enabled':False})
        assert disabled.status_code == 200 and managed.get('/auth/me').status_code == 401
        assert login_http(managed, temporary, name='Synthetic.Admin').status_code == 401
        restored = admin.patch(f"/api/users/{account['id']}", headers=headers, json={'expected_updated_at':disabled.json()['updated_at'], 'is_enabled':True})
        assert restored.status_code == 200
        with engine.connect() as c:
            events = sql(c, "SELECT action,before_values,after_values FROM audit_events WHERE entity_type='users' AND entity_key=:id", id=str(account['id'])).mappings().all()
            assert {'user_created','user_role_changed','user_password_reset','user_disabled','user_reactivated'} <= {row['action'] for row in events}
            assert temporary not in repr(events) and reset not in repr(events)


def test_concurrent_account_edits_reject_stale_state(auth_env):
    from asi_meal_api.user_management import UserService
    from asi_meal_api.orders import ActorContext, Conflict
    engine, g, _, auth_service, _, _, _ = auth_env
    with engine.begin() as c:
        sql(c, "UPDATE users SET role_code='super_admin' WHERE id=:id", id=g['actor'])
    users = UserService(auth_service.session_factory, auth_service.passwords)
    context = ActorContext(g['actor'])
    target = users.create(context, 'Synthetic.Concurrent', 'Synthetic', 'admin', secrets.token_urlsafe(24))
    def change(display):
        try:
            users.change(context, target['id'], target['updated_at'], display, None, None)
            return 'saved'
        except Conflict:
            return 'stale'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(change, ['Synthetic One', 'Synthetic Two'])) == ['saved', 'stale']


def test_password_change_migration_preserves_existing_accounts(postgres):
    schema = f"migration_{uuid4().hex}"
    with postgres.engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = create_engine(postgres.engine.url, hide_parameters=True, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as c:
            command.upgrade(alembic_config(c), '0004_super_admin')
            account_id = sql(c, "INSERT INTO users (login_name,display_name,password_hash,role_code) VALUES ('Synthetic.Existing','Synthetic','synthetic-hash','admin') RETURNING id").scalar_one()
            command.upgrade(alembic_config(c), 'head')
            row = sql(c, 'SELECT role_code,password_hash,password_change_required FROM users WHERE id=:id', id=account_id).one()
            assert row == ('admin', 'synthetic-hash', False)
    finally:
        engine.dispose()
        with postgres.engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')


def test_password_change_revokes_other_sessions_and_reset_revokes_current(auth_env):
    engine, g, _, service, password, _, runtime = auth_env
    with engine.begin() as c:
        sql(c, "UPDATE users SET role_code='super_admin' WHERE id=:id", id=g['actor'])
    old, new, reset = (secrets.token_urlsafe(24) for _ in range(3))
    origin = {'Origin': 'https://testserver'}
    with client(runtime) as admin, client(runtime) as first, client(runtime) as second:
        admin_headers = {**origin, 'X-CSRF-Token': login_http(admin, password).json()['csrf_token']}
        account = admin.post('/api/users', headers=admin_headers, json={'login_name':'Synthetic.Sessions', 'display_name':'Synthetic', 'role':'admin', 'temporary_password':old}).json()
        one = login_http(first, old, name='Synthetic.Sessions').json()
        two = login_http(second, old, name='Synthetic.Sessions').json()
        one_headers = {**origin, 'X-CSRF-Token': one['csrf_token']}
        assert first.post('/auth/change-password', headers=one_headers, json={'current_password':old, 'new_password':new}).status_code == 200
        assert first.get('/auth/me').status_code == 200
        assert second.get('/auth/me').status_code == 401
        account = next(u for u in admin.get('/api/users').json() if u['id'] == account['id'])
        assert admin.patch(f"/api/users/{account['id']}", headers=admin_headers, json={'expected_updated_at':account['updated_at'], 'temporary_password':reset}).status_code == 200
        assert first.get('/auth/me').status_code == 401
        assert login_http(second, reset, name='Synthetic.Sessions').json()['user']['password_change_required']
