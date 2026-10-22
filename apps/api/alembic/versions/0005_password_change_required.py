"""Track mandatory password changes without affecting existing accounts."""

from alembic import op
import sqlalchemy as sa

revision = "0005_password_change_required"
down_revision = "0004_super_admin"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("password_change_required", sa.Boolean(), nullable=False,
                                     server_default=sa.false()))


def downgrade():
    op.drop_column("users", "password_change_required")
