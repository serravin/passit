"""Add analytics timestamps and operational AI usage, preserving unknown history."""

import sqlalchemy as sa
from alembic import op

revision = "946cac341da2"
down_revision = "2817241ad1ba"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("users", "likes", "work_items"):
        op.add_column(table, sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index(f"ix_{table}_created_at", table, ["created_at"])
    op.add_column("chains", sa.Column("setup_ai_assisted", sa.Boolean(), nullable=True))
    op.add_column("chains", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_chains_completed_at", "chains", ["completed_at"])
    # Final submitted turns provide real completion times; never invent signup/like times.
    op.execute(
        sa.text(
            "UPDATE chains SET completed_at = (SELECT MAX(submitted_at) FROM turns WHERE turns.chain_id = chains.id) WHERE status = 'completed'"
        )
    )
    op.add_column("ai_profiles", sa.Column("input_price_per_million", sa.Numeric(16, 6), nullable=True))
    op.add_column("ai_profiles", sa.Column("output_price_per_million", sa.Numeric(16, 6), nullable=True))
    op.create_table(
        "analytics_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(sa.text("INSERT INTO analytics_state (id, started_at) VALUES (1, CURRENT_TIMESTAMP)"))
    op.create_table(
        "ai_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("ai_profiles.id"), nullable=True),
        sa.Column("chain_id", sa.String(36), sa.ForeignKey("chains.id"), nullable=True),
        sa.Column("work_item_id", sa.String(36), sa.ForeignKey("work_items.id"), nullable=True),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("task", sa.String(30), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("is_retry", sa.Boolean(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(18, 8), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
    )
    for field in ("started_at", "chain_id", "work_item_id"):
        op.create_index(f"ix_ai_calls_{field}", "ai_calls", [field])


def downgrade():
    op.drop_table("ai_calls")
    op.drop_table("analytics_state")
    for field in ("input_price_per_million", "output_price_per_million"):
        op.drop_column("ai_profiles", field)
    op.drop_index("ix_chains_completed_at", "chains")
    op.drop_column("chains", "completed_at")
    op.drop_column("chains", "setup_ai_assisted")
    for table in ("users", "likes", "work_items"):
        op.drop_index(f"ix_{table}_created_at", table)
        op.drop_column(table, "created_at")
