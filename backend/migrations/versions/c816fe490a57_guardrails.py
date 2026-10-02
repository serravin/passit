"""Add safety reviews, account notices, and quarantine unchecked legacy stories."""

import hashlib
import json
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "c816fe490a57"
down_revision = "b4833cfe029a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ai_calls", sa.Column("operation_key", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("guardrail_block_id", sa.String(36), nullable=True))
    op.add_column("chains", sa.Column("safety_origin", sa.String(20), nullable=True))
    op.add_column("turns", sa.Column("safety_origin", sa.String(20), nullable=True))
    with op.batch_alter_table("user_moderation_events") as batch:
        batch.alter_column("admin_id", existing_type=sa.String(36), nullable=True)
        batch.add_column(sa.Column("source", sa.String(20), server_default="admin", nullable=False))
    with op.batch_alter_table("user_moderation_events") as batch:
        batch.alter_column("source", server_default=None)
    op.add_column(
        "chains", sa.Column("safety_status", sa.String(20), server_default="pending", nullable=False)
    )
    with op.batch_alter_table(
        "chains",
        table_args=(
            sa.CheckConstraint(
                "2 <= min_participants AND min_participants <= max_participants",
                name="chains_participant_limits",
            ),
            sa.CheckConstraint("turn_timeout_seconds > 0", name="chains_positive_timeout"),
        )
        if op.get_bind().dialect.name == "sqlite"
        else (),
    ) as batch:
        batch.alter_column("safety_status", server_default=None)
    op.create_index("ix_chains_safety_status", "chains", ["safety_status"])
    op.create_table(
        "safety_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("ai_profiles.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("chain_id", sa.String(36), sa.ForeignKey("chains.id"), nullable=True),
        sa.Column("turn_id", sa.String(36), sa.ForeignKey("turns.id"), nullable=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("review_status", sa.String(20), nullable=False),
        sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("chain_id", "review_status", "created_at"):
        op.create_index(f"ix_safety_reviews_{column}", "safety_reviews", [column])
    op.create_table(
        "account_notices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_account_notices_user_id", "account_notices", ["user_id"])
    op.create_table(
        "generated_text_proofs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("turn_id", sa.String(36), sa.ForeignKey("turns.id"), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
    )
    for column in ("user_id", "content_hash"):
        op.create_index(f"ix_generated_text_proofs_{column}", "generated_text_proofs", [column])
    # Preserve hashes of previously delivered suggestions so old drafts cannot be blamed on their player.
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, user_id, suggestions FROM turns WHERE status <> 'submitted'"))
    for turn_id, user_id, suggestions in rows:
        suggestions = json.loads(suggestions) if isinstance(suggestions, str) else suggestions
        for candidate in suggestions or []:
            conn.execute(
                sa.text(
                    "INSERT INTO generated_text_proofs (id, user_id, turn_id, kind, content_hash) VALUES (:id, :user_id, :turn_id, 'suggestion', :digest)"
                ),
                {
                    "id": str(uuid4()),
                    "user_id": user_id,
                    "turn_id": turn_id,
                    "digest": hashlib.sha256(candidate.strip().encode()).hexdigest(),
                },
            )
    # Regenerate unfinished suggestions under the new guardrail, preserving the original deadlines.
    op.execute(
        sa.text(
            "UPDATE work_items SET status='pending', attempts=0, available_at=CURRENT_TIMESTAMP, lease_token=NULL, lease_until=NULL, error_code=NULL WHERE task='suggestions' AND aggregate_id IN (SELECT id FROM turns WHERE status <> 'submitted')"
        )
    )
    op.execute(sa.text("UPDATE turns SET suggestions=NULL, fallback_index=NULL WHERE status <> 'submitted'"))


def downgrade():
    op.drop_table("generated_text_proofs")
    op.drop_column("ai_calls", "operation_key")
    op.drop_table("account_notices")
    op.drop_table("safety_reviews")
    op.drop_index("ix_chains_safety_status", "chains")
    with op.batch_alter_table("chains") as batch:
        batch.drop_column("safety_status")
        batch.drop_column("safety_origin")
    op.drop_column("turns", "safety_origin")
    # Automated events have no administrator and cannot fit the old schema.
    op.execute(sa.text("DELETE FROM user_moderation_events WHERE admin_id IS NULL"))
    with op.batch_alter_table("user_moderation_events") as batch:
        batch.drop_column("source")
        batch.alter_column("admin_id", existing_type=sa.String(36), nullable=False)
    op.drop_column("users", "guardrail_block_id")
