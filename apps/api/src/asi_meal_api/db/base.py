"""Shared SQLAlchemy registry and exact monetary binding."""

from decimal import Decimal

from sqlalchemy import MetaData, Numeric
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Money(TypeDecorator[Decimal]):
    """Reject lossy application inputs before PostgreSQL numeric can round them."""

    impl = Numeric(12, 2)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (Decimal, int)):
            raise ValueError("Money must be Decimal or an integer, never float")
        value = Decimal(value)
        if not value.is_finite() or abs(value) > Decimal("9999999999.99"):
            raise ValueError("Money must be finite and fit numeric(12,2)")
        if value != value.quantize(Decimal("0.01")):
            raise ValueError("Money cannot have fractional centavos")
        return value
