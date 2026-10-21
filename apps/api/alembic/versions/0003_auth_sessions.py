"""Approved persistent sessions; previous revisions remain frozen."""

from alembic import op
import sqlalchemy as sa

revision = "0003_auth_sessions"
down_revision = "0002_reference_data"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("csrf_token", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT", onupdate="RESTRICT",
                                name="fk_auth_sessions_user_id_users"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        sa.CheckConstraint("octet_length(token_hash) = 32 AND octet_length(csrf_token) = 32", name="ck_auth_sessions_token_lengths"),
        sa.CheckConstraint("isfinite(created_at) AND isfinite(last_seen_at) AND isfinite(expires_at) "
                           "AND (revoked_at IS NULL OR isfinite(revoked_at))", name="ck_auth_sessions_finite_times"),
        sa.CheckConstraint("expires_at > created_at AND last_seen_at >= created_at AND last_seen_at <= expires_at "
                           "AND (revoked_at IS NULL OR revoked_at >= created_at)", name="ck_auth_sessions_time_order"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])


def downgrade():
    # Explicit rollback path for disposable tests; real downgrades need approval.
    op.drop_table("auth_sessions")
