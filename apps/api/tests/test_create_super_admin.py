"""Tests for the interactive local Super Admin creation command."""
from test_auth import auth_env, passwords  # noqa: F401 - registers shared fixtures
from test_orders import concurrent_env  # noqa: F401 - registers the shared fixture
from test_database import sql


def test_create_super_admin_is_interactive_atomic_and_duplicate_safe(auth_env, monkeypatch, capsys):
    from asi_meal_api import auth_cli

    engine, _, _, _, _, _, _ = auth_env
    monkeypatch.setenv("ASI_DATABASE_URL", "postgresql+psycopg://synthetic")
    monkeypatch.setattr(auth_cli, "create_engine", lambda *a, **kw: engine)
    monkeypatch.setattr(engine, "dispose", lambda: None)
    monkeypatch.setattr(auth_cli.sys.stdin, "isatty", lambda: True)
    values = iter(["Synthetic operator", "Synthetic demo setup", "CREATE superadmin"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(values))
    monkeypatch.setattr(auth_cli.getpass, "getpass", lambda prompt: "SyntheticSuper123")

    assert auth_cli.main(["create-super-admin"]) == 0
    with engine.connect() as connection:
        row = sql(connection, "SELECT login_name,display_name,role_code,is_enabled,password_change_required FROM users WHERE login_name='superadmin'").one()
        audit = sql(connection, "SELECT action,reason,after_values FROM audit_events WHERE action='super_admin_created'").one()
    assert tuple(row) == ("superadmin", "master_emman", "super_admin", True, True)
    assert audit[0] == "super_admin_created" and audit[1] == "Synthetic demo setup"
    assert audit[2]["attribution"] == "local_self_attested"
    assert "SyntheticSuper123" not in capsys.readouterr().out

    values = iter(["Synthetic operator", "Duplicate attempt", "CREATE superadmin"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(values))
    assert auth_cli.main(["create-super-admin"]) == 1
    with engine.connect() as connection:
        assert sql(connection, "SELECT count(*) FROM users WHERE login_name='superadmin'").scalar_one() == 1
        assert sql(connection, "SELECT count(*) FROM audit_events WHERE action='super_admin_created'").scalar_one() == 1


def test_create_super_admin_refuses_noninteractive(auth_env, monkeypatch):
    from asi_meal_api import auth_cli

    engine, _, _, _, _, _, _ = auth_env
    monkeypatch.setenv("ASI_DATABASE_URL", "postgresql+psycopg://synthetic")
    monkeypatch.setattr(auth_cli, "create_engine", lambda *a, **kw: engine)
    monkeypatch.setattr(engine, "dispose", lambda: None)
    monkeypatch.setattr(auth_cli.sys.stdin, "isatty", lambda: False)
    assert auth_cli.main(["create-super-admin"]) == 1
