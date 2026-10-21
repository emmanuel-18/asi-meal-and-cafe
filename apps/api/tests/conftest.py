"""Opt-in PostgreSQL tests always create their own verified disposable container.

No external database URL is accepted. Credentials exist only in process memory
and the temporary container environment, never in source or diagnostic output.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine, URL


API_ROOT = Path(__file__).resolve().parents[1]

# Exact public surface: business operations must remain protected, and no user
# provisioning, audit-history, price-override or snapshot-edit routes are exposed.
EXPECTED_HTTP_ROUTES = {
    "/health": {"get"}, "/auth/login": {"post"}, "/auth/logout": {"post"}, "/auth/me": {"get"},
    "/api/employees": {"get"}, "/api/employees/import": {"post"},
    "/api/visitors": {"get", "post"}, "/api/dishes": {"get", "post"},
    "/api/menus": {"post"}, "/api/menus/{menu_id}/dates": {"put"},
    "/api/menus/by-date/{service_date}": {"get"},
    "/api/menus/{menu_id}": {"get"},
    "/api/orders": {"get", "post"}, "/api/orders/{order_id}": {"get", "patch"},
    "/api/orders/{order_id}/received": {"post"}, "/api/orders/{order_id}/reverse-received": {"post"},
    "/api/reports/sales": {"get"}, "/api/reports/payments": {"get"},
    "/api/reports/salary-deduction": {"get"}, "/api/reports/bundle": {"get"},
}


def pytest_addoption(parser):
    parser.addoption("--postgres", action="store_true", help="Provision isolated PostgreSQL 17 tests")


def docker(*args, env=None):
    result = subprocess.run(
        ["docker", *args], env=env, capture_output=True, text=True, timeout=180,
    )
    if result.returncode:
        # Do not echo commands, environment, container inspection, or credentials.
        raise RuntimeError("Disposable Docker operation failed; check Docker availability")
    return result.stdout.strip()


def alembic_config(connection):
    config = Config(str(API_ROOT / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


@dataclass
class DisposableDatabase:
    engine: Engine
    container_name: str

    def migrate(self, revision="head"):
        with self.engine.begin() as connection:
            command.upgrade(alembic_config(connection), revision)


@pytest.fixture(scope="session")
def postgres(request):
    if not request.config.getoption("--postgres"):
        pytest.skip("PostgreSQL integration requires --postgres (new disposable container only)")
    nonce = uuid4().hex
    name = f"asi-meal-stage1-test-{nonce}"
    database = f"asi_meal_test_{nonce}"
    username = f"test_{nonce}"
    env = {**os.environ, "POSTGRES_PASSWORD": secrets.token_urlsafe(32)}
    container_id = None
    engine = None
    try:
        container_id = docker(
            "run", "--detach", "--rm", "--name", name,
            "--label", f"asi.meal.test-run={nonce}",
            "--label", "asi.meal.disposable=true",
            "--tmpfs", "/var/lib/postgresql/data:rw",
            "--publish", "127.0.0.1::5432",
            "--env", f"POSTGRES_USER={username}",
            "--env", f"POSTGRES_DB={database}",
            "--env", "POSTGRES_PASSWORD", "postgres:17", env=env,
        )
        info = json.loads(docker("inspect", container_id))[0]
        # Verify isolation BEFORE creating an engine or making a DB connection.
        assert info["Id"] == container_id
        assert info["Name"] == f"/{name}"
        assert info["Config"]["Image"] == "postgres:17"
        assert info["Config"]["Labels"]["asi.meal.test-run"] == nonce
        assert info["Config"]["Labels"]["asi.meal.disposable"] == "true"
        # Docker may list --tmpfs only in HostConfig, not in Mounts.
        assert info["HostConfig"]["Tmpfs"] == {"/var/lib/postgresql/data": "rw"}
        assert not info["HostConfig"].get("Binds")
        assert all(m["Type"] == "tmpfs" and m["Destination"] == "/var/lib/postgresql/data"
                   for m in info["Mounts"])
        binding = info["NetworkSettings"]["Ports"]["5432/tcp"]
        assert len(binding) == 1 and binding[0]["HostIp"] == "127.0.0.1"
        assert not info["Config"]["Labels"].get("com.docker.compose.project")
        for _ in range(90):
            result = subprocess.run(
                ["docker", "exec", container_id, "pg_isready", "-U", username, "-d", database],
                capture_output=True, timeout=10,
            )
            if result.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become ready")
        engine = create_engine(
            URL.create("postgresql+psycopg", username=username,
                       password=env["POSTGRES_PASSWORD"], host="127.0.0.1",
                       port=int(binding[0]["HostPort"]), database=database),
            hide_parameters=True,
        )
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT current_database()").scalar_one() == database
            version = int(connection.exec_driver_sql("SHOW server_version_num").scalar_one())
            assert 170000 <= version < 180000
            assert inspect(connection).get_table_names() == []
        print(f"Verified {name}: PostgreSQL 17, tmpfs only, fresh empty DB, loopback port; no Compose volume")
        target = DisposableDatabase(engine, name)
        target.migrate()
        yield target
    finally:
        if engine is not None:
            engine.dispose()
        if container_id:
            # Only this run's exact created ID; no volume or broad resource deletion.
            docker("rm", "--force", container_id)


@pytest.fixture
def db(postgres):
    with postgres.engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()
