from decimal import Decimal

import pytest
from sqlalchemy.orm import configure_mappers

from asi_meal_api.db import Base, models
from asi_meal_api.db.base import Money


def test_all_eighteen_models_configure_without_connection():
    configure_mappers()
    assert len(Base.registry.mappers) == len(Base.metadata.tables) == 18
    assert "payment_allocations" in Base.metadata.tables
    assert "paid_status" not in models.Order.__table__.columns
    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            assert foreign_key.ondelete == "RESTRICT"
    assert models.OrderItem.__table__.c.line_total.computed.persisted


@pytest.mark.parametrize("bad", [1.5, True, "1.00", Decimal("NaN"), Decimal("Infinity"),
                                     Decimal("1.001"), Decimal("10000000000")])
def test_money_rejects_lossy_or_nonfinite_inputs(bad):
    with pytest.raises(ValueError):
        Money().process_bind_param(bad, None)


def test_money_keeps_exact_decimal_values():
    assert Money().process_bind_param(Decimal("245.00"), None) == Decimal("245.00")
    assert Money().process_bind_param(50, None) == Decimal("50")
