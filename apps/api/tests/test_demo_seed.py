from datetime import date
from uuid import UUID

import pytest

from asi_meal_api.demo_seed import NAMESPACE, SeedError, _plan, _safe_target, _verify_database_target
from asi_meal_api import demo_seed


def test_plan_is_deterministic_and_balanced_statuses():
    args = type("Args", (), {"seed": 7, "start": date(2026, 10, 24), "days": 6, "orders": 10, "visitors": 3})()
    first = _plan(args)
    second = _plan(args)
    assert first == second
    assert len(first["orders"]) == 10
    assert sum(item["status"] == "received" for item in first["orders"]) == 8
    assert all(UUID(item["request_key"]).version == 5 for item in first["orders"])
    assert all(item["request_key"] == str(UUID(item["request_key"])) for item in first["orders"])


def test_target_refuses_protected_and_non_loopback_origins():
    _safe_target("http://127.0.0.1:43871")
    with pytest.raises(SeedError):
        _safe_target("https://192.168.45.145:43873")
    with pytest.raises(SeedError):
        _safe_target("http://127.0.0.1:43872")


def test_database_target_requires_named_isolated_database(monkeypatch):
    monkeypatch.setenv("ASI_DATABASE_URL", "postgresql+psycopg://user:secret@127.0.0.1:58149/asi_demo_438864ebc209")
    monkeypatch.setenv("ASI_DEMO_CONTAINER", "asi-meal-demo-postgres-438864ebc209")
    _verify_database_target("asi_demo_438864ebc209")
    monkeypatch.setenv("ASI_DATABASE_URL", "postgresql+psycopg://user:secret@192.168.45.145:43873/production")
    with pytest.raises(SeedError):
        _verify_database_target("asi_demo_438864ebc209")


def test_existing_dated_menu_is_reused(monkeypatch, tmp_path):
    class Client:
        def login(self, password):
            pass

        def request(self, method, path, body=None):
            if path.startswith('/api/employees'):
                return [{'employee_number': 'SYN-1'}]
            if path.startswith('/api/dishes'):
                return [{'id': 1, 'category_code': 'vegetable'}, {'id': 2, 'category_code': 'non_vegetable'}]
            if path.startswith('/api/menus/by-date/'):
                return {'id': 42, 'service_date': '2026-10-24', 'items': []}
            pytest.fail(f'unexpected request: {method} {path}')

        def close(self):
            pass

    monkeypatch.setattr(demo_seed, 'DemoClient', Client)
    monkeypatch.setattr(demo_seed, '_verify_database_target', lambda _: None)
    monkeypatch.setattr(demo_seed.getpass, 'getpass', lambda _: 'synthetic')
    args = type('Args', (), {'database_name': 'test', 'journal': tmp_path / 'journal', 'phase': 'pilot'})()
    demo_seed._apply({'service_dates': ['2026-10-24'], 'visitors': [], 'orders': []}, args)
