from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_offline_migrations_are_complete_without_a_database(monkeypatch):
    monkeypatch.delenv("ASI_DATABASE_URL", raising=False)
    output = StringIO()
    config = Config(str(ROOT / "alembic.ini"), output_buffer=output)
    command.upgrade(config, "head", sql=True)
    script = output.getvalue()
    assert script.count("CREATE TABLE ") == 19  # 18 models plus Alembic tracking.
    assert "CREATE CONSTRAINT TRIGGER asi_order_totals" in script
    assert "orders%ROWTYPE" in script and "orders%%ROWTYPE" not in script
    assert "'assistant_admin'" in script and "'extra_rice'" in script
    assert "INSERT INTO users" not in script and "INSERT INTO employees" not in script


def test_online_migrations_require_explicit_connection_configuration(monkeypatch):
    monkeypatch.delenv("ASI_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="Set ASI_DATABASE_URL explicitly"):
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
