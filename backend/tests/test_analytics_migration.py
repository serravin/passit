from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


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
    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT setup FROM chains WHERE id='c'")) == "Keep this private story"
        assert conn.scalar(text("SELECT text FROM turns WHERE id='t'")) == "A private ending"
        assert conn.scalar(text("SELECT completed_at FROM chains WHERE id='c'")) == "2026-01-02 11:10:00"
        for table in ("users", "likes", "work_items"):
            assert conn.scalar(text(f"SELECT created_at FROM {table}")) is None
        assert conn.scalar(text("SELECT COUNT(*) FROM analytics_state")) == 1
        assert conn.scalar(text("SELECT COUNT(*) FROM ai_calls")) == 0
    command.downgrade(config, "2817241ad1ba")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT COUNT(*) FROM chains")) == 1
    engine.dispose()
