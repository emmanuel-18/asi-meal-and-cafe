"""Recovery uses only the disposable PostgreSQL fixture and synthetic accounts."""
import pytest
from test_auth import auth_env, passwords
from test_orders import concurrent_env
from test_database import sql
from asi_meal_api.auth import AuthenticationFailed


def test_recovery_cli_atomic_and_restricted(auth_env, monkeypatch, capsys):
    from asi_meal_api import auth_cli
    engine, g, _, service, old_password, _, _ = auth_env
    monkeypatch.setenv('ASI_DATABASE_URL', 'postgresql+psycopg://synthetic')
    monkeypatch.setattr(auth_cli, 'create_engine', lambda *a, **kw: engine)
    monkeypatch.setattr(engine, 'dispose', lambda: None)
    monkeypatch.setattr(auth_cli.sys.stdin, 'isatty', lambda: True)
    temporary = 'SyntheticRecovery123'

    def run(login='Synthetic.Login', confirmation=None, password=temporary, reason='Synthetic recovery reason'):
        entries = iter([login, 'Synthetic operator', reason, confirmation or f"RECOVER {g['actor']}"])
        monkeypatch.setattr('builtins.input', lambda prompt: next(entries))
        monkeypatch.setattr(auth_cli.getpass, 'getpass', lambda prompt: password)
        return auth_cli.main(['recover-super-admin'])

    assert run() == 1  # Admin cannot be recovered by this command.
    assert run(login='missing') == 1
    with engine.begin() as c:
        sql(c, "UPDATE users SET role_code='super_admin', is_enabled=false WHERE id=:id", id=g['actor'])
    assert run() == 1
    with engine.begin() as c:
        sql(c, "UPDATE users SET is_enabled=true WHERE id=:id", id=g['actor'])
    first = service.login('Synthetic.Login', old_password)
    second = service.login('Synthetic.Login', old_password)
    assert run(confirmation='cancel') == 1
    assert run(password='seven77') == 1
    assert run(reason='short') == 1
    assert service.current(first.token)
    monkeypatch.setattr(auth_cli.sys.stdin, 'isatty', lambda: False)
    assert auth_cli.main(['recover-super-admin']) == 1
    monkeypatch.setattr(auth_cli.sys.stdin, 'isatty', lambda: True)
    # A changed target between review and commit must not be recovered.
    entries = iter(['Synthetic.Login', 'Synthetic operator', 'Synthetic recovery reason', f"RECOVER {g['actor']}"])
    monkeypatch.setattr('builtins.input', lambda prompt: next(entries))
    def changed_target(prompt):
        with engine.begin() as c:
            sql(c, "UPDATE users SET display_name='Changed synthetic name' WHERE id=:id", id=g['actor'])
        return temporary
    monkeypatch.setattr(auth_cli.getpass, 'getpass', changed_target)
    assert auth_cli.main(['recover-super-admin']) == 1
    assert service.current(first.token)
    # Simulate audit insertion failure: account and session changes must roll back.
    original_event = auth_cli.event
    monkeypatch.setattr(auth_cli, 'event', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('failure')))
    assert run() == 1
    assert service.current(first.token)
    monkeypatch.setattr(auth_cli, 'event', original_event)
    assert run() == 0
    for old in (first, second):
        with pytest.raises(AuthenticationFailed): service.current(old.token)
    recovered = service.login('Synthetic.Login', temporary)
    assert recovered.user.password_change_required
    with engine.connect() as c:
        row = sql(c, "SELECT role_code,is_enabled,password_change_required FROM users WHERE id=:id", id=g['actor']).one()
        assert tuple(row) == ('super_admin', True, True)
        events = sql(c, "SELECT before_values,after_values,reason FROM audit_events WHERE action='super_admin_recovered'").mappings().all()
        assert len(events) == 1
        assert events[0]['after_values']['attribution'] == 'local_self_attested'
        assert temporary not in repr(events) and old_password not in repr(events)
    output = capsys.readouterr()
    assert temporary not in output.out + output.err and old_password not in output.out + output.err
