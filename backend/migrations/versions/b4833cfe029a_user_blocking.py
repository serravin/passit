"""Add account blocks and a private administrator action history."""

import sqlalchemy as sa
from alembic import op

revision = "b4833cfe029a"
down_revision = "946cac341da2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("block_reason", sa.String(500), nullable=True))
    op.create_index("ix_users_blocked_at", "users", ["blocked_at"])
    op.create_table(
        "user_moderation_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("admin_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("user_id", "created_at"):
        op.create_index(f"ix_user_moderation_events_{column}", "user_moderation_events", [column])


def downgrade():
    op.drop_table("user_moderation_events")
    op.drop_index("ix_users_blocked_at", "users")
    op.drop_column("users", "block_reason")
    op.drop_column("users", "blocked_at")
