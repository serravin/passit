from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return str(uuid4())


def now():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    issuer: Mapped[str] = mapped_column(String(500))
    subject: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(80))
    color: Mapped[str] = mapped_column(String(20), default="#fbbf24")
    admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=now, index=True)
    __table_args__ = (UniqueConstraint("issuer", "subject"),)


class UserSettings(Base):
    __tablename__ = "user_settings"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    allow_random_participation: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    language: Mapped[str] = mapped_column(String(8), default="en")


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PlatformSettings(Base):
    __tablename__ = "platform_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    max_participants_per_chain: Mapped[int] = mapped_column(Integer, default=20)
    __table_args__ = (CheckConstraint("max_participants_per_chain >= 2"),)


class Friendship(Base):
    __tablename__ = "friendships"
    left_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    right_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (CheckConstraint("left_id < right_id"),)


class Group(Base):
    __tablename__ = "groups"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(80))


class GroupMember(Base):
    __tablename__ = "group_members"
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)


class Chain(Base):
    __tablename__ = "chains"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str | None] = mapped_column(String(100))
    setup: Mapped[str] = mapped_column(Text)
    setup_ai_assisted: Mapped[bool | None] = mapped_column(Boolean, default=False)
    rules: Mapped[str] = mapped_column(String(500), default="")
    group_mode: Mapped[str] = mapped_column(String(20))
    source_group_id: Mapped[str | None] = mapped_column(ForeignKey("groups.id"))
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    visibility: Mapped[str] = mapped_column(String(20), default="participants_only")
    publication_status: Mapped[str] = mapped_column(String(20), default="not_requested")
    publication_requester_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    publication_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    turn_timeout_seconds: Mapped[int] = mapped_column(Integer, default=900)
    min_participants: Mapped[int] = mapped_column(Integer, default=2)
    max_participants: Mapped[int] = mapped_column(Integer, default=5)
    __table_args__ = (
        CheckConstraint("2 <= min_participants AND min_participants <= max_participants"),
        CheckConstraint("turn_timeout_seconds > 0"),
    )


class Participant(Base):
    __tablename__ = "participants"
    chain_id: Mapped[str] = mapped_column(ForeignKey("chains.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    contributed: Mapped[bool] = mapped_column(Boolean, default=False)


class Motive(Base):
    __tablename__ = "motives"
    id: Mapped[str] = mapped_column(String(30), primary_key=True)
    label: Mapped[str] = mapped_column(String(80))
    emoji: Mapped[str] = mapped_column(String(10))


class Turn(Base):
    __tablename__ = "turns"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    chain_id: Mapped[str] = mapped_column(ForeignKey("chains.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    position: Mapped[int] = mapped_column(Integer)
    motive_id: Mapped[str] = mapped_column(ForeignKey("motives.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    text: Mapped[str | None] = mapped_column(Text)
    ai_assisted: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    suggestions: Mapped[list | None] = mapped_column(JSON)
    fallback_index: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("chain_id", "position"),
        UniqueConstraint("chain_id", "user_id"),
        Index(
            "one_active_turn",
            "chain_id",
            unique=True,
            sqlite_where=(status != "submitted"),
            postgresql_where=(status != "submitted"),
        ),
        CheckConstraint("NOT (ai_assisted AND ai_generated)"),
    )


class Approval(Base):
    __tablename__ = "approvals"
    chain_id: Mapped[str] = mapped_column(ForeignKey("chains.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    decision: Mapped[str] = mapped_column(String(20), default="pending")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Like(Base):
    __tablename__ = "likes"
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=now, index=True)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    chain_id: Mapped[str | None] = mapped_column(ForeignKey("chains.id"))
    turn_id: Mapped[str | None] = mapped_column(ForeignKey("turns.id"))
    __table_args__ = (
        CheckConstraint(
            "(chain_id IS NOT NULL AND turn_id IS NULL) OR (chain_id IS NULL AND turn_id IS NOT NULL)"
        ),
        UniqueConstraint("user_id", "chain_id"),
        UniqueConstraint("user_id", "turn_id"),
    )


class AIProfile(Base):
    __tablename__ = "ai_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    revision: Mapped[int] = mapped_column(Integer, unique=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    provider: Mapped[str] = mapped_column(String(30))
    endpoint: Mapped[str] = mapped_column(String(500), default="")
    deployment_name: Mapped[str] = mapped_column(String(100), default="")
    model_reference: Mapped[str] = mapped_column(String(100), default="")
    api_version: Mapped[str] = mapped_column(String(40), default="2024-10-21")
    auth_mode: Mapped[str] = mapped_column(String(30), default="managed_identity")
    credential_reference: Mapped[str] = mapped_column(String(100), default="PASSIT_AI_API_KEY")
    generation_parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    request_timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    input_price_per_million: Mapped[float | None] = mapped_column(Numeric(16, 6))
    output_price_per_million: Mapped[float | None] = mapped_column(Numeric(16, 6))
    prompt_version: Mapped[str] = mapped_column(String(20), default="v1")
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIAssignment(Base):
    __tablename__ = "ai_assignments"
    task: Mapped[str] = mapped_column(String(20), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey("ai_profiles.id"))


class WorkItem(Base):
    """Transactional outbox with durable local delivery; replace transport with Service Bus on Azure."""

    __tablename__ = "work_items"
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=now, index=True)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    key: Mapped[str] = mapped_column(String(200), unique=True)
    task: Mapped[str] = mapped_column(String(30))
    aggregate_id: Mapped[str] = mapped_column(String(36))
    profile_id: Mapped[str | None] = mapped_column(ForeignKey("ai_profiles.id"))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    chain_id: Mapped[str] = mapped_column(ForeignKey("chains.id"))
    message: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class AnalyticsState(Base):
    __tablename__ = "analytics_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AICall(Base):
    """Operational metadata only: never store prompts, responses, credentials or user text."""

    __tablename__ = "ai_calls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    profile_id: Mapped[str | None] = mapped_column(ForeignKey("ai_profiles.id"))
    chain_id: Mapped[str | None] = mapped_column(ForeignKey("chains.id"), index=True)
    work_item_id: Mapped[str | None] = mapped_column(ForeignKey("work_items.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    task: Mapped[str] = mapped_column(String(30))
    purpose: Mapped[str] = mapped_column(String(20), default="game")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer)
    succeeded: Mapped[bool] = mapped_column(Boolean)
    is_retry: Mapped[bool] = mapped_column(Boolean, default=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Numeric(18, 8))
    error_code: Mapped[str | None] = mapped_column(String(80))
