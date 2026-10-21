"""Approved vocabulary only. No accounts or business data."""

from decimal import Decimal

from alembic import op
import sqlalchemy as sa

revision = "0002_reference_data"
down_revision = "0001_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.bulk_insert(
        sa.table("roles", sa.column("code", sa.Text), sa.column("display_name", sa.Text)),
        [
            {"code": "admin", "display_name": "Admin"},
            {"code": "assistant_admin", "display_name": "Assistant Admin"},
        ],
    )
    op.bulk_insert(
        sa.table("item_categories", sa.column("code", sa.Text),
                 sa.column("display_name", sa.Text), sa.column("default_unit_price", sa.Numeric(12, 2))),
        [
            {"code": "vegetable", "display_name": "Vegetable meal (including rice)", "default_unit_price": Decimal("50.00")},
            {"code": "non_vegetable", "display_name": "Non-vegetable meal (including rice)", "default_unit_price": Decimal("75.00")},
            {"code": "extra_rice", "display_name": "Extra rice", "default_unit_price": Decimal("15.00")},
        ],
    )
    op.bulk_insert(
        sa.table("payment_categories", sa.column("code", sa.Text), sa.column("display_name", sa.Text)),
        [{"code": code, "display_name": label} for code, label in [
            ("cash", "Cash"), ("gcash", "GCash"), ("sd", "Salary Deduction (SD)"),
            ("incentive", "Incentive"), ("finance", "Finance"),
        ]],
    )


def downgrade():
    # Restrictive FKs prevent removal if business rows depend on these codes.
    op.execute("DELETE FROM payment_categories WHERE code IN ('cash','gcash','sd','incentive','finance')")
    op.execute("DELETE FROM item_categories WHERE code IN ('vegetable','non_vegetable','extra_rice')")
    op.execute("DELETE FROM roles WHERE code IN ('admin','assistant_admin')")
