from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_upgrade_preserves_stories_and_does_not_invent_historical_dates(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/legacy.db"
    monkeypatch.setenv("PASSIT_DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "2817241ad1ba")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, issuer, subject, name, color, admin) VALUES ('u', 'demo', 'legacy', 'Legacy', '#ffffff', 0)"
            )
        )
        conn.execute(text("INSERT INTO motives (id, label, emoji) VALUES ('end', 'End the story', 'x')"))
        conn.execute(
            text(
                """INSERT INTO chains (id, creator_id, setup, rules, group_mode, status, visibility, publication_status, created_at, turn_timeout_seconds, min_participants, max_participants) VALUES ('c', 'u', 'Keep this private story', '', 'friends', 'completed', 'participants_only', 'not_requested', '2026-01-01 12:00:00', 900, 2, 5)"""
            )
        )
        conn.execute(
            text(
                """INSERT INTO turns (id, chain_id, user_id, position, motive_id, status, assigned_at, deadline_at, submitted_at, text, ai_assisted, ai_generated) VALUES ('t', 'c', 'u', 1, 'end', 'submitted', '2026-01-02 11:00:00', '2026-01-02 12:00:00', '2026-01-02 11:10:00', 'A private ending', 0, 0)"""
            )
        )
        conn.execute(text("INSERT INTO likes (id, user_id, chain_id) VALUES ('l', 'u', 'c')"))
        conn.execute(
            text(
                """INSERT INTO work_items (id, key, task, aggregate_id, payload, status, available_at, attempts) VALUES ('w', 'legacy', 'handoff', 'c', '{}', 'done', '2026-01-01 12:00:00', 1)"""
            )
        )
        conn.execute(
            text(
                "INSERT INTO users (id, issuer, subject, name, color, admin) VALUES ('v', 'demo', 'second', 'Second', '#ffffff', 0)"
            )
        )
        conn.execute(
            text(
                """INSERT INTO turns (id, chain_id, user_id, position, motive_id, status, assigned_at, deadline_at, suggestions, fallback_index, ai_assisted, ai_generated) VALUES ('a', 'c', 'v', 2, 'end', 'assigned', '2026-01-02 11:00:00', '2026-01-02 12:00:00', '["Old AI draft","Second","Third"]', 0, 0, 0)"""
            )
        )
        conn.execute(
            text(
                """INSERT INTO work_items (id, key, task, aggregate_id, payload, status, available_at, attempts) VALUES ('p', 'prepared', 'suggestions', 'a', '{}', 'done', '2026-01-01 12:00:00', 1)"""
            )
        )
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT setup FROM chains WHERE id='c'")) == "Keep this private story"
        assert conn.scalar(text("SELECT text FROM turns WHERE id='t'")) == "A private ending"
        assert conn.scalar(text("SELECT completed_at FROM chains WHERE id='c'")) == "2026-01-02 11:10:00"
        assert conn.scalar(text("SELECT setup_ai_assisted FROM chains WHERE id='c'")) is None
        assert conn.scalar(text("SELECT blocked_at FROM users WHERE id='u'")) is None
        assert conn.scalar(text("SELECT block_reason FROM users WHERE id='u'")) is None
        assert conn.scalar(text("SELECT COUNT(*) FROM user_moderation_events")) == 0
        for table in ("users", "likes", "work_items"):
            assert conn.scalar(text(f"SELECT created_at FROM {table}")) is None
        assert conn.scalar(text("SELECT COUNT(*) FROM analytics_state")) == 1
        assert conn.scalar(text("SELECT COUNT(*) FROM ai_calls")) == 0
        assert conn.scalar(text("SELECT safety_status FROM chains WHERE id='c'")) == "pending"
        assert conn.scalar(text("SELECT COUNT(*) FROM account_notices")) == 0
        assert conn.scalar(text("SELECT COUNT(*) FROM safety_reviews")) == 0
        assert conn.scalar(text("SELECT COUNT(*) FROM generated_text_proofs WHERE turn_id='a'")) == 3
        assert conn.scalar(text("SELECT suggestions FROM turns WHERE id='a'")) is None
        assert conn.scalar(text("SELECT deadline_at FROM turns WHERE id='a'")) == "2026-01-02 12:00:00"
        assert conn.scalar(text("SELECT status FROM work_items WHERE id='p'")) == "pending"
        assert len(inspect(conn).get_check_constraints("chains")) == 2
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("UPDATE chains SET min_participants=1 WHERE id='c'"))
    command.downgrade(config, "2817241ad1ba")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT COUNT(*) FROM chains")) == 1
    engine.dispose()
