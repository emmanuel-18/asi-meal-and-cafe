"""Add the Super Admin role without changing existing users."""

from alembic import op
import sqlalchemy as sa

revision = "0004_super_admin"
down_revision = "0003_auth_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(op.f("ck_roles_code_allowed"), "roles", type_="check")
    op.create_check_constraint(
        op.f("ck_roles_code_allowed"), "roles",
        "code IN ('admin', 'assistant_admin', 'super_admin')",
    )
    op.bulk_insert(sa.table("roles", sa.column("code", sa.Text), sa.column("display_name", sa.Text)),
                   [{"code": "super_admin", "display_name": "Super Admin"}])


def downgrade():
    # The FK prevents deleting this role while any account still references it.
    op.execute("DELETE FROM roles WHERE code = 'super_admin'")
    op.drop_constraint(op.f("ck_roles_code_allowed"), "roles", type_="check")
    op.create_check_constraint(op.f("ck_roles_code_allowed"), "roles", "code IN ('admin', 'assistant_admin')")
