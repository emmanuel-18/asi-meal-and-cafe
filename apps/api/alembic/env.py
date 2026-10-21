"""Explicit migrations only. No application imports or implicit database URL."""

import os

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.dialects.postgresql import JSONB

from asi_meal_api.db import Base
from asi_meal_api.db.base import Money

config = context.config


def render_item(kind, item, autogen_context):
    if kind == "type" and isinstance(item, Money):
        return "sa.Numeric(precision=12, scale=2)"
    if kind == "type" and isinstance(item, JSONB):
        autogen_context.imports.add("from sqlalchemy.dialects import postgresql")
        return "postgresql.JSONB()"
    return False


def configure(connection):
    context.configure(
        connection=connection, target_metadata=Base.metadata,
        compare_type=True, render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        dialect_name="postgresql", target_metadata=Base.metadata,
        literal_binds=True, compare_type=True, dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get("connection") is not None:
    configure(config.attributes["connection"])
else:
    database_url = os.environ.get("ASI_DATABASE_URL")
    if not database_url:
        raise RuntimeError("Set ASI_DATABASE_URL explicitly before running migrations")
    if not database_url.startswith("postgresql+psycopg://"):
        raise RuntimeError("Migrations require a PostgreSQL psycopg URL")
    engine = create_engine(database_url, poolclass=pool.NullPool, hide_parameters=True)
    try:
        with engine.connect() as connection:
            configure(connection)
    finally:
        engine.dispose()
