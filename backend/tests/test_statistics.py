import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from fastapi import HTTPException
from passit.ai import CreativeAI
from passit.analytics import report, reporting_periods
from passit.config import Settings
from passit.models import AICall, AIProfile, AnalyticsState, Chain, Like, Participant, Turn, WorkItem
from passit.schemas import ProfileInput
from passit.telemetry import measured_generate
from sqlalchemy import select

from .conftest import login


def at(day, hour=10):
    return datetime(2026, 10, day, hour, tzinfo=UTC)


def test_statistics_require_admin_and_validate_range(game):
    client, _, _, users = game
    assert client.get("/api/admin/statistics").status_code == 401
    login(client, users[1])
    assert client.get("/api/admin/statistics").status_code == 403
    login(client, users[0])
    assert client.get("/api/admin/statistics?preset=today&timezone=Europe/Berlin").status_code == 200
    for query in (
        "preset=unknown",
        "timezone=Not/AZone",
        "preset=custom",
        "preset=custom&start=2026-10-10&end=2026-10-01",
        "preset=custom&start=2026-10-01&end=2099-01-01",
        "preset=custom&start=invalid&end=2026-10-01",
    ):
        assert client.get("/api/admin/statistics?" + query).status_code == 422, query


def test_periods_timezone_dst_and_equivalent_comparison(game):
    _, db, _, _ = game
    with db.sessions() as s:
        current, old, _ = reporting_periods(
            s,
            "custom",
            date(2026, 3, 29),
            date(2026, 3, 29),
            "Europe/Berlin",
            datetime(2026, 3, 30, 12, tzinfo=UTC),
        )
        assert (current.end - current.start) == timedelta(hours=23)
        assert (old.end - old.start) == timedelta(hours=24)
        current, old, _ = reporting_periods(s, "mtd", snapshot=datetime(2026, 3, 31, 13, tzinfo=UTC))
        assert current.start_date == date(2026, 3, 1)
        assert old.start_date == date(2026, 2, 1) and old.end_date == date(2026, 2, 28)
        assert old.end.hour == 13
        current, old, _ = reporting_periods(s, "this_week", snapshot=at(15, 12))
        assert current.start_date.weekday() == 0 and old.start_date == current.start_date - timedelta(days=7)
        current, old, _ = reporting_periods(s, "all_time", snapshot=at(15))
        assert old is None
        with pytest.raises(HTTPException):
            reporting_periods(s, "custom", date(1969, 1, 1), date(2026, 1, 1), snapshot=at(15))


def test_metrics_activity_cohorts_retention_cost_and_privacy(game):
    _, db, _, users = game
    alex, jamie, sam, morgan, riley = users
    with db.transaction() as s:
        for user in users:
            s.merge(user).created_at = datetime(2026, 9, 1, tzinfo=UTC)
        s.merge(alex).created_at = at(1, 9)
        s.merge(sam).created_at = at(4, 9)
        s.merge(morgan).created_at = at(10, 9)
        s.get(AnalyticsState, 1).started_at = datetime(2026, 9, 1, tzinfo=UTC)
        stories = []
        for day in (1, 2, 8):
            chain = Chain(
                creator_id=alex.id,
                created_at=at(day),
                setup="PRIVATE_CONTENT_DO_NOT_RETURN",
                rules="SECRET_RULES",
                group_mode="friends",
            )
            s.add(chain)
            s.flush()
            for user in (alex, jamie, sam):
                s.add(Participant(chain_id=chain.id, user_id=user.id, contributed=True))
            stories.append(chain)
        stories[1].setup_ai_assisted = True
        stories[2].setup_ai_assisted = None  # Historical setup assistance was not recorded.
        chain = stories[0]
        chain.status = "completed"
        chain.completed_at = at(5)
        chain.published_at = at(9)
        chain.publication_requested_at = at(6)
        chain.publication_status = "approved"
        automatic = Turn(
            chain_id=chain.id,
            user_id=jamie.id,
            position=1,
            motive_id="worse",
            status="submitted",
            assigned_at=at(3) - timedelta(minutes=5),
            deadline_at=at(3),
            submitted_at=at(3),
            ai_generated=True,
            text="PRIVATE_AUTOMATIC_TEXT",
        )
        human = Turn(
            chain_id=chain.id,
            user_id=sam.id,
            position=2,
            motive_id="end",
            status="submitted",
            assigned_at=at(5) - timedelta(minutes=2),
            deadline_at=at(5) + timedelta(minutes=13),
            submitted_at=at(5),
            ai_assisted=True,
            text="PRIVATE_HUMAN_TEXT",
        )
        s.add_all([automatic, human])
        s.flush()
        s.add_all(
            [
                Like(user_id=riley.id, chain_id=chain.id, created_at=at(9)),
                Like(user_id=riley.id, turn_id=human.id, created_at=at(9)),
            ]
        )
        s.add(
            AICall(
                chain_id=chain.id,
                provider="azure_openai",
                task="suggestions",
                started_at=at(3),
                duration_ms=100,
                succeeded=True,
                input_tokens=100,
                output_tokens=50,
                estimated_cost_usd=0.15,
            )
        )
        s.add(
            AICall(
                chain_id=chain.id,
                provider="azure_openai",
                task="title",
                started_at=at(4),
                duration_ms=300,
                succeeded=False,
                is_retry=True,
            )
        )
    with db.sessions() as s:
        data = report(
            s, preset="custom", start_date=date(2026, 10, 1), end_date=date(2026, 10, 10), snapshot=at(15)
        )
    metrics = data["current"]["metrics"]
    assert metrics["active_users"] == 2  # A fallback never makes its assigned user active.
    assert metrics["new_users"] == 3 and metrics["activation_rate"] == 66.67
    assert metrics["activation_hours"] == 13
    assert metrics["stories_started"] == 3 and metrics["stories_completed"] == 1
    assert metrics["completion_rate"] == 33.33 and metrics["cohort_in_progress"] == 2
    assert metrics["avg_players"] == 3
    assert metrics["contributions"] == 5 and metrics["human_written"] == 1
    assert metrics["ai_assisted"] == 2 and metrics["automatic"] == 1
    assert metrics["unclassified_setups"] == 1
    assert metrics["timeout_rate"] == 50 and metrics["response_minutes"] == 2
    assert metrics["stories_per_active_user"] == 2 and metrics["repeat_player_rate"] == 50
    assert metrics["repeat_groups"] == 1
    assert metrics["retention_d1"] == 50 and metrics["retention_d7"] == 50
    assert metrics["retention_d30"] is None
    assert data["current"]["funnel"] == {"started": 3, "handoff": 1, "completed": 1, "published": 1}
    assert metrics["story_likes"] == metrics["contribution_likes"] == 1
    assert metrics["ai_calls"] == 2 and metrics["ai_failures"] == metrics["ai_retry_calls"] == 1
    assert metrics["input_tokens"] is None and metrics["ai_cost_usd"] is None
    assert metrics["cost_per_completed_story"] is None
    assert metrics["mrr"] is None
    assert sum(day["started"] for day in data["series"]) == 3
    assert "PRIVATE" not in json.dumps(data) and "SECRET" not in json.dumps(data)
    assert not any(user.id in json.dumps(data) for user in users)
    # Retention uses follow-up activity after the selected cohort period ends.
    with db.sessions() as s:
        short = report(
            s, preset="custom", start_date=date(2026, 10, 1), end_date=date(2026, 10, 1), snapshot=at(15)
        )
    assert short["current"]["metrics"]["retention_d7"] == 100


def test_empty_rates_and_missing_historical_usage_are_unavailable(game):
    _, db, _, _ = game
    with db.sessions() as s:
        data = report(
            s, preset="custom", start_date=date(2026, 1, 1), end_date=date(2026, 1, 2), snapshot=at(15)
        )
    metrics = data["current"]["metrics"]
    assert metrics["active_users"] == 0
    assert metrics["completion_rate"] is None and metrics["activation_rate"] is None
    assert metrics["ai_calls"] is None and metrics["ai_cost_usd"] is None
    assert data["coverage"]["ai_partial_history"]


def test_azure_usage_cost_schema_errors_and_retries_are_recorded_without_content(game, monkeypatch):
    _, db, _, _ = game
    with db.transaction() as s:
        profile = AIProfile(
            revision=2,
            provider="azure_openai",
            endpoint="https://ai.example",
            deployment_name="test",
            auth_mode="environment_reference",
            input_price_per_million=2,
            output_price_per_million=4,
        )
        s.add(profile)
        s.flush()
        job = WorkItem(key="usage-test", task="title", aggregate_id="unused", profile_id=profile.id)
        s.add(job)
        s.flush()
    settings = Settings(ai_allowed_hosts={"ai.example"})
    monkeypatch.setenv("PASSIT_AI_API_KEY", "fake-test-key")
    response = {
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        "choices": [{"message": {"content": '{"title":"PRIVATE_TITLE"}'}}],
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response))
    client_type = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client_type(transport=transport, **kwargs))
    adapter = CreativeAI(settings)
    assert (
        measured_generate(db, adapter, profile, "title", {}, work_item_id=job.id)["title"] == "PRIVATE_TITLE"
    )
    response["choices"][0]["message"]["content"] = '{"title":""}'
    with pytest.raises(ValueError):
        measured_generate(db, adapter, profile, "title", {}, work_item_id=job.id)
    with db.sessions() as s:
        rows = list(s.scalars(select(AICall).order_by(AICall.started_at)))
        assert len(rows) == 2 and rows[0].succeeded and not rows[1].succeeded
        assert not rows[0].is_retry and rows[1].is_retry
        assert float(rows[0].estimated_cost_usd) == 0.0004
        assert rows[1].input_tokens == 100 and float(rows[1].estimated_cost_usd) == 0.0004
        assert "PRIVATE" not in str([row.__dict__ for row in rows])
    for price in (-1, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            ProfileInput(input_price_per_million=price)
