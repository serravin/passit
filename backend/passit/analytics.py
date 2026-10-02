"""Aggregate admin reporting. Queries select metadata, never private story content."""

from calendar import monthrange
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from statistics import median
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select

from .domain import fail, utc
from .models import AICall, AnalyticsState, Chain, Like, Participant, Turn, User, WorkItem, now

PRESETS = {"today", "this_week", "mtd", "ytd", "last7", "last30", "all_time", "custom"}


@dataclass
class Period:
    start: datetime
    end: datetime
    start_date: date
    end_date: date
    zone: ZoneInfo

    def contains(self, value):
        return value is not None and self.start <= utc(value) < self.end

    def view(self):
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "start": self.start.isoformat(),
            "end_exclusive": self.end.isoformat(),
        }


def reporting_periods(s, preset, start_date=None, end_date=None, timezone="UTC", snapshot=None):
    snapshot = utc(snapshot or now())
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        fail("Choose a valid reporting timezone", 422)
    if preset not in PRESETS:
        fail("Choose a valid reporting period", 422)
    local_now = snapshot.astimezone(zone)
    today = local_now.date()
    if preset == "custom":
        if not start_date or not end_date:
            fail("Choose both a start and an end date", 422)
    else:
        end_date = today
        start_date = {
            "today": today,
            "this_week": today - timedelta(days=today.weekday()),
            "mtd": today.replace(day=1),
            "ytd": today.replace(month=1, day=1),
            "last7": today - timedelta(days=6),
            "last30": today - timedelta(days=29),
        }.get(preset)
        if preset == "all_time":
            earliest = [s.scalar(select(func.min(column))) for column in (Chain.created_at, User.created_at)]
            earliest = [utc(value) for value in earliest if value]
            start_date = min(earliest).astimezone(zone).date() if earliest else today
            start_date = min(start_date, today)
    if start_date > end_date or end_date > today or start_date.year < 1970:
        fail("Choose an ordered date range ending no later than today (1970 or later)", 422)

    def boundary(day):
        return datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC)

    current = Period(
        boundary(start_date),
        min(boundary(end_date + timedelta(days=1)), snapshot),
        start_date,
        end_date,
        zone,
    )
    previous = None
    if preset != "all_time":
        days = (end_date - start_date).days + 1
        if preset == "this_week":
            old_start, old_end = start_date - timedelta(days=7), end_date - timedelta(days=7)
        elif preset in {"mtd", "ytd"}:
            year, month = (
                (today.year - (today.month == 1), today.month - 1 or 12)
                if preset == "mtd"
                else (today.year - 1, today.month)
            )
            old_end = date(year, month, min(today.day, monthrange(year, month)[1]))
            old_start = old_end.replace(day=1) if preset == "mtd" else old_end.replace(month=1, day=1)
        else:
            old_start, old_end = start_date - timedelta(days=days), end_date - timedelta(days=days)
        # Compare the same elapsed local day when the selected period includes today.
        old_end_exclusive = boundary(old_end + timedelta(days=1))
        if end_date == today:
            old_end_exclusive = datetime.combine(old_end, local_now.timetz(), tzinfo=zone).astimezone(UTC)
        previous = Period(boundary(old_start), old_end_exclusive, old_start, old_end, zone)
    return current, previous, snapshot


def percent(numerator, denominator):
    return round(100 * numerator / denominator, 2) if denominator else None


def typical(values):
    return round(median(values), 2) if values else None


def report(s, *, preset="mtd", start_date=None, end_date=None, timezone="UTC", snapshot=None):
    period, previous, snapshot = reporting_periods(s, preset, start_date, end_date, timezone, snapshot)
    state = s.get(AnalyticsState, 1)
    tracking_since = utc(state.started_at) if state else snapshot
    # Read only IDs, timestamps and numerical/status metadata. No names or story text.
    users = s.execute(select(User.id, User.created_at)).mappings().all()
    chains = (
        s.execute(
            select(
                Chain.id,
                Chain.creator_id,
                Chain.setup_ai_assisted,
                Chain.created_at,
                Chain.completed_at,
                Chain.published_at,
                Chain.publication_requested_at,
                Chain.publication_status,
                Chain.status,
            ).where(Chain.created_at < snapshot)
        )
        .mappings()
        .all()
    )
    turns = (
        s.execute(
            select(
                Turn.chain_id,
                Turn.user_id,
                Turn.assigned_at,
                Turn.deadline_at,
                Turn.submitted_at,
                Turn.ai_assisted,
                Turn.ai_generated,
            ).where(Turn.assigned_at < snapshot)
        )
        .mappings()
        .all()
    )
    memberships = s.execute(select(Participant.chain_id, Participant.user_id)).all()
    likes = s.execute(select(Like.created_at, Like.chain_id, Like.turn_id)).mappings().all()
    jobs = s.execute(select(WorkItem.created_at, WorkItem.status)).mappings().all()
    calls = (
        s.execute(
            select(
                AICall.chain_id,
                AICall.provider,
                AICall.started_at,
                AICall.succeeded,
                AICall.purpose,
                AICall.duration_ms,
                AICall.is_retry,
                AICall.input_tokens,
                AICall.output_tokens,
                AICall.estimated_cost_usd,
            ).where(AICall.started_at < snapshot)
        )
        .mappings()
        .all()
    )
    activities = [(c["creator_id"], c["id"], utc(c["created_at"])) for c in chains]
    activities += [
        (t["user_id"], t["chain_id"], utc(t["submitted_at"]))
        for t in turns
        if t["submitted_at"] and not t["ai_generated"] and utc(t["submitted_at"]) < snapshot
    ]
    first_play = {}
    play_days = defaultdict(set)
    for user_id, _, at in activities:
        first_play[user_id] = min(first_play.get(user_id, at), at)
        play_days[user_id].add(at.astimezone(period.zone).date())
    members = defaultdict(set)
    for chain_id, user_id in memberships:
        members[chain_id].add(user_id)
    per_chain_calls = defaultdict(list)
    for call in calls:
        if call["chain_id"] and call["purpose"] == "game":
            per_chain_calls[call["chain_id"]].append(call)

    history_intact = (
        all(u["created_at"] and utc(u["created_at"]) >= tracking_since for u in users)
        and all(utc(c["created_at"]) >= tracking_since for c in chains)
        and all(job["created_at"] and utc(job["created_at"]) >= tracking_since for job in jobs)
    )
    missing_signups = sum(u["created_at"] is None for u in users)
    missing_likes = sum(like["created_at"] is None for like in likes)
    missing_jobs = sum(job["created_at"] is None for job in jobs)

    def calculate(window, all_time=False):
        cohort = [c for c in chains if window.contains(c["created_at"])]
        completed = [c for c in chains if window.contains(c["completed_at"])]
        settled = [t for t in turns if window.contains(t["submitted_at"])]
        human = [t for t in settled if not t["ai_generated"]]
        automatic = len(settled) - len(human)
        plays = [(u, c, at) for u, c, at in activities if window.contains(at)]
        active = {u for u, _, _ in plays}
        played_stories = defaultdict(set)
        for u, c, _ in plays:
            played_stories[u].add(c)
        registered = [u for u in users if window.contains(u["created_at"])]
        activated = [
            u
            for u in registered
            if u["id"] in first_play and utc(u["created_at"]) <= first_play[u["id"]] < window.end
        ]
        activation_hours = [
            (first_play[u["id"]] - utc(u["created_at"])).total_seconds() / 3600 for u in activated
        ]
        cohort_ids = {c["id"] for c in cohort}
        handoffs = {
            t["chain_id"] for t in turns if t["chain_id"] in cohort_ids and utc(t["assigned_at"]) < window.end
        }
        cohort_completed = [c for c in cohort if c["completed_at"] and utc(c["completed_at"]) < window.end]
        cohort_published = [c for c in cohort if c["published_at"] and utc(c["published_at"]) < window.end]
        submitted_time = [
            (utc(t["submitted_at"]) - utc(t["assigned_at"])).total_seconds() / 60 for t in human
        ]
        repeat_casts = Counter(tuple(sorted(members[c["id"]])) for c in cohort)
        selected_calls = [c for c in calls if window.contains(c["started_at"])]
        coverage_complete = window.end > tracking_since and (window.start >= tracking_since or history_intact)
        usage_complete = coverage_complete and all(
            c["input_tokens"] is not None and c["output_tokens"] is not None for c in selected_calls
        )
        priced = coverage_complete and all(c["estimated_cost_usd"] is not None for c in selected_calls)
        costs = [
            c
            for c in completed
            if utc(c["created_at"]) >= tracking_since
            and per_chain_calls[c["id"]]
            and all(call["estimated_cost_usd"] is not None for call in per_chain_calls[c["id"]])
        ]
        measured_cost = sum(
            float(call["estimated_cost_usd"]) for c in costs for call in per_chain_calls[c["id"]]
        )
        selected_likes = [
            like
            for like in likes
            if window.contains(like["created_at"]) or all_time and like["created_at"] is None
        ]
        selected_jobs = [
            job
            for job in jobs
            if window.contains(job["created_at"]) or all_time and job["created_at"] is None
        ]
        metrics = {
            "new_users": len(registered),
            "active_users": len(active),
            "stories_started": len(cohort),
            "stories_completed": len(completed),
            "stories_published": sum(window.contains(c["published_at"]) for c in chains),
            "cohort_in_progress": sum(
                not c["completed_at"] or utc(c["completed_at"]) >= window.end for c in cohort
            ),
            "completion_rate": percent(len(cohort_completed), len(cohort)),
            "avg_players": round(sum(len(members[c["id"]]) for c in cohort) / len(cohort), 2)
            if cohort
            else None,
            "contributions": len(cohort) + len(settled),
            "human_written": sum(c["setup_ai_assisted"] is False for c in cohort)
            + sum(not t["ai_assisted"] for t in human),
            "ai_assisted": sum(c["setup_ai_assisted"] is True for c in cohort)
            + sum(t["ai_assisted"] for t in human),
            "unclassified_setups": sum(c["setup_ai_assisted"] is None for c in cohort),
            "automatic": automatic,
            "activation_rate": percent(len(activated), len(registered)),
            "activation_hours": typical(activation_hours),
            "response_minutes": typical(submitted_time),
            "timeout_rate": percent(automatic, len(settled)),
            "completion_hours": typical(
                [(utc(c["completed_at"]) - utc(c["created_at"])).total_seconds() / 3600 for c in completed]
            ),
            "stories_per_active_user": round(sum(len(cs) for cs in played_stories.values()) / len(active), 2)
            if active
            else None,
            "repeat_player_rate": percent(sum(len(cs) > 1 for cs in played_stories.values()), len(active)),
            "repeat_groups": sum(count > 1 for count in repeat_casts.values()),
            "story_likes": sum(like["chain_id"] is not None for like in selected_likes),
            "contribution_likes": sum(like["turn_id"] is not None for like in selected_likes),
            "jobs_queued": len(selected_jobs),
            "failed_jobs": sum(job["status"] == "failed" for job in selected_jobs),
            "ai_calls": len(selected_calls) if window.end > tracking_since else None,
            "ai_failures": sum(not c["succeeded"] for c in selected_calls)
            if window.end > tracking_since
            else None,
            "ai_retry_calls": sum(c["is_retry"] for c in selected_calls)
            if window.end > tracking_since
            else None,
            "ai_failure_rate": percent(sum(not c["succeeded"] for c in selected_calls), len(selected_calls)),
            "ai_latency_ms": typical([c["duration_ms"] for c in selected_calls]),
            "input_tokens": sum(c["input_tokens"] for c in selected_calls) if usage_complete else None,
            "output_tokens": sum(c["output_tokens"] for c in selected_calls) if usage_complete else None,
            "ai_cost_usd": round(sum(float(c["estimated_cost_usd"]) for c in selected_calls), 6)
            if priced
            else None,
            "cost_per_completed_story": round(measured_cost / len(costs), 6)
            if costs and len(costs) == len(completed)
            else None,
            "validation_calls": sum(c["purpose"] == "validation" for c in selected_calls),
            "demo_calls": sum(c["provider"] == "demo" for c in selected_calls),
            "paying_users": None,
            "paid_conversion": None,
            "mrr": None,
            "cancellations": None,
        }
        if window.start < tracking_since and not all_time:
            if missing_signups:
                metrics["new_users"] = metrics["activation_rate"] = metrics["activation_hours"] = None
            if missing_likes:
                metrics["story_likes"] = metrics["contribution_likes"] = None
            if missing_jobs:
                metrics["jobs_queued"] = metrics["failed_jobs"] = None
        retention = []
        as_of_date = snapshot.astimezone(window.zone).date()
        for day in (1, 7, 30):
            eligible = [
                u
                for u, at in first_play.items()
                if window.contains(at)
                and at.astimezone(window.zone).date() + timedelta(days=day) < as_of_date
            ]
            returned = sum(
                first_play[u].astimezone(window.zone).date() + timedelta(days=day) in play_days[u]
                for u in eligible
            )
            rate = percent(returned, len(eligible))
            metrics[f"retention_d{day}"] = rate
            retention.append({"day": day, "eligible": len(eligible), "returned": returned, "rate": rate})
        # A settled turn's timeout result is compared by its original allowed duration.
        deadline_rows = []
        for key, low, high in (
            ("under5", 0, 300),
            ("5to15", 300, 900),
            ("15to60", 900, 3600),
            ("over60", 3600, float("inf")),
        ):
            rows = [
                t
                for t in settled
                if low < (utc(t["deadline_at"]) - utc(t["assigned_at"])).total_seconds() <= high
            ]
            deadline_rows.append(
                {
                    "bucket": key,
                    "turns": len(rows),
                    "timeout_rate": percent(sum(t["ai_generated"] for t in rows), len(rows)),
                }
            )
        # Publication state uses recorded decision times, rather than today's mutable state.
        from .models import Approval

        rejected_at = dict(
            s.execute(
                select(Approval.chain_id, func.min(Approval.decided_at))
                .where(Approval.decision == "rejected")
                .group_by(Approval.chain_id)
            ).all()
        )
        requests = [c for c in chains if window.contains(c["publication_requested_at"])]
        metrics["publication_pending"] = sum(
            (not c["published_at"] or utc(c["published_at"]) >= window.end)
            and (c["id"] not in rejected_at or utc(rejected_at[c["id"]]) >= window.end)
            for c in requests
        )
        metrics["publication_approved"] = sum(window.contains(c["published_at"]) for c in chains)
        metrics["publication_declined"] = sum(window.contains(at) for at in rejected_at.values())
        return {
            "metrics": metrics,
            "retention": retention,
            "deadlines": deadline_rows,
            "funnel": {
                "started": len(cohort),
                "handoff": len(handoffs),
                "completed": len(cohort_completed),
                "published": len(cohort_published),
            },
            "cost_coverage": {"completed": len(completed), "covered": len(costs)},
        }

    current = calculate(period, preset == "all_time")
    old = calculate(previous) if previous else None
    return {
        "period": {**period.view(), "preset": preset, "timezone": timezone},
        "comparison": previous.view() if previous else None,
        "generated_at": snapshot.isoformat(),
        "tracking_since": tracking_since.isoformat(),
        "current": current,
        "previous": old,
        "totals": {"users": len(users), "stories": s.scalar(select(func.count()).select_from(Chain))},
        "coverage": {
            "users_without_signup_date": missing_signups,
            "likes_without_date": missing_likes,
            "jobs_without_date": missing_jobs,
            "ai_partial_history": period.start < tracking_since
            and (not history_intact or period.end <= tracking_since),
        },
        **chart(period, chains),
    }


def chart(period, chains):
    days = (period.end_date - period.start_date).days + 1
    granularity = "day" if days <= 120 else "week" if days <= 730 else "month"

    def bucket(day):
        if granularity == "week":
            day -= timedelta(days=day.weekday())
        elif granularity == "month":
            day = day.replace(day=1)
        return max(period.start_date, day)

    series = {}
    day = period.start_date
    while day <= period.end_date:
        key = bucket(day).isoformat()
        series.setdefault(key, {"date": key, "started": 0, "completed": 0, "published": 0})
        if granularity == "month":
            day = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            day += timedelta(days=1 if granularity == "day" else 7 - day.weekday())
    for chain in chains:
        for column, field in (
            ("created_at", "started"),
            ("completed_at", "completed"),
            ("published_at", "published"),
        ):
            at = chain[column]
            if period.contains(at):
                series[bucket(utc(at).astimezone(period.zone).date()).isoformat()][field] += 1
    return {"granularity": granularity, "series": list(series.values())}
