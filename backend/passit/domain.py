import secrets
from datetime import UTC, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select

from .models import (
    AIAssignment,
    Approval,
    Chain,
    Friendship,
    Group,
    GroupMember,
    Motive,
    Notification,
    Participant,
    PlatformSettings,
    Turn,
    UserSettings,
    WorkItem,
    now,
    uid,
)


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def fail(message, status=409):
    raise HTTPException(status, message)


def require_member(s, chain_id, user_id, allow_published=False):
    chain = s.get(Chain, chain_id)
    if not chain:
        fail("Story not found", 404)
    if allow_published and chain.visibility == "published" and chain.status == "completed":
        return chain
    if not user_id or not s.get(Participant, (chain_id, user_id)):
        fail("Story not found", 404)
    return chain


def lock_chain(s, chain_id):
    chain = s.scalar(select(Chain).where(Chain.id == chain_id).with_for_update())
    if not chain:
        fail("Story not found", 404)
    return chain


def queue(s, task, aggregate, key, payload=None, available_at=None):
    if s.scalar(select(WorkItem).where(WorkItem.key == key)):
        return
    profile_id = None
    if task in {"handoff", "suggestions", "title", "setup"}:
        assignment = s.get(AIAssignment, task) or s.get(AIAssignment, "default")
        if not assignment:
            fail("An administrator must activate an AI profile before starting a Chain", 503)
        profile_id = assignment.profile_id
    s.add(
        WorkItem(
            task=task,
            aggregate_id=aggregate,
            key=key,
            profile_id=profile_id,
            payload=payload or {},
            available_at=available_at or now(),
        )
    )
    s.flush()


def notify(s, user_id, chain_id, message):
    preferences = s.get(UserSettings, user_id)
    if preferences and preferences.notifications_enabled:
        s.add(Notification(user_id=user_id, chain_id=chain_id, message=message))


def friends(s, user_id):
    rows = s.scalars(
        select(Friendship).where(
            (Friendship.left_id == user_id) | (Friendship.right_id == user_id),
            Friendship.status == "accepted",
        )
    )
    return {row.right_id if row.left_id == user_id else row.left_id for row in rows}


def validate_group(s, owner_id, member_ids):
    chosen = set(member_ids)
    if len(chosen) != len(member_ids):
        fail("Select each friend once", 422)
    if chosen - friends(s, owner_id) - {owner_id}:
        fail("Groups can only contain your friends", 422)
    return chosen | {owner_id}


def launch(s, creator, data):
    cap = s.scalar(
        select(PlatformSettings).where(PlatformSettings.id == 1).with_for_update()
    ).max_participants_per_chain
    maximum = data.max_participants if data.max_participants is not None else min(5, cap)
    if not 2 <= data.min_participants <= maximum <= cap:
        fail(f"Use 2 ≤ minimum ≤ maximum ≤ {cap}", 422)
    members = set(data.member_ids)
    if len(members) != len(data.member_ids) or creator.id in members:
        fail("Select each participant once; the creator is already included", 422)
    if data.group_mode == "friends":
        if members - friends(s, creator.id):
            fail("Select participants from your friends", 422)
        members.add(creator.id)
    elif data.group_mode == "saved_group":
        group = s.get(Group, data.source_group_id)
        if not group or not s.get(GroupMember, (group.id, creator.id)):
            fail("Saved group not found", 404)
        saved = set(s.scalars(select(GroupMember.user_id).where(GroupMember.group_id == group.id)))
        if members and members - saved:
            fail("Selected subset must belong to the saved group", 422)
        members = (members if members else saved) | {creator.id}
    elif data.group_mode == "random":
        if data.member_ids or data.source_group_id:
            fail("Random groups are chosen by the system", 422)
        eligible = list(
            s.scalars(
                select(UserSettings.user_id).where(
                    UserSettings.allow_random_participation.is_(True), UserSettings.user_id != creator.id
                )
            )
        )
        secrets.SystemRandom().shuffle(eligible)
        members = set(eligible[: maximum - 1]) | {creator.id}
    if data.group_mode != "saved_group" and data.source_group_id:
        fail("Source group applies only to saved groups", 422)
    if not data.min_participants <= len(members) <= maximum:
        fail(
            "Group size must fit the participant limits; larger saved groups require a subset or a higher maximum",
            422,
        )
    chain = Chain(
        id=uid(),
        creator_id=creator.id,
        setup=data.setup,
        rules=data.rules,
        group_mode=data.group_mode,
        source_group_id=data.source_group_id,
        turn_timeout_seconds=data.turn_timeout_seconds,
        min_participants=data.min_participants,
        max_participants=maximum,
    )
    s.add(chain)
    s.flush()
    for user_id in members:
        s.add(Participant(chain_id=chain.id, user_id=user_id, contributed=user_id == creator.id))
        s.add(Approval(chain_id=chain.id, user_id=user_id))
        notify(s, user_id, chain.id, "You’re in a new Chain. The first pass is being prepared.")
    s.flush()
    queue(s, "handoff", chain.id, f"handoff:{chain.id}:0")
    return chain


def story_context(s, chain):
    turns = list(
        s.scalars(
            select(Turn).where(Turn.chain_id == chain.id, Turn.status == "submitted").order_by(Turn.position)
        )
    )
    remaining = s.scalar(
        select(func.count())
        .select_from(Participant)
        .where(Participant.chain_id == chain.id, Participant.contributed.is_(False))
    )
    return {
        "setup": chain.setup,
        "story": [chain.setup] + [t.text for t in turns],
        "used_motives": [t.motive_id for t in turns],
        "remaining": remaining,
        "rules": chain.rules,
        "eligible_motives": [m.id for m in s.scalars(select(Motive)) if remaining == 1 or m.id != "end"],
    }


def assign(s, chain, motive_id, timestamp=None):
    if chain.status != "active" or s.scalar(
        select(Turn).where(Turn.chain_id == chain.id, Turn.status != "submitted")
    ):
        return
    eligible = list(
        s.scalars(
            select(Participant).where(Participant.chain_id == chain.id, Participant.contributed.is_(False))
        )
    )
    if not eligible:
        chain.status = "completed"
        return
    if motive_id == "end" and len(eligible) != 1:
        raise ValueError("End motive requires the final participant")
    participant = secrets.choice(eligible)
    timestamp = timestamp or now()
    position = s.scalar(select(func.count()).select_from(Turn).where(Turn.chain_id == chain.id)) + 1
    turn = Turn(
        id=uid(),
        chain_id=chain.id,
        user_id=participant.user_id,
        position=position,
        motive_id=motive_id,
        assigned_at=timestamp,
        deadline_at=timestamp + timedelta(seconds=chain.turn_timeout_seconds),
    )
    s.add(turn)
    s.flush()
    queue(s, "suggestions", turn.id, f"suggestions:{turn.id}")
    queue(s, "timeout", turn.id, f"timeout:{turn.id}", available_at=turn.deadline_at)
    if position == 1 and not chain.title:
        queue(s, "title", chain.id, f"title:{chain.id}", payload=story_context(s, chain))
    notify(s, participant.user_id, chain.id, "Your turn! Add your part and pass it on.")


def complete_turn(s, chain, turn, text, assisted=False, generated=False, timestamp=None):
    if turn.status == "submitted":
        return False
    timestamp = timestamp or now()
    turn.text = text
    turn.ai_assisted = assisted
    turn.ai_generated = generated
    turn.submitted_at = timestamp
    turn.status = "submitted"
    turn.suggestions = None
    turn.fallback_index = None
    s.get(Participant, (chain.id, turn.user_id)).contributed = True
    s.flush()
    remaining = s.scalar(
        select(func.count())
        .select_from(Participant)
        .where(Participant.chain_id == chain.id, Participant.contributed.is_(False))
    )
    if remaining:
        queue(s, "handoff", chain.id, f"handoff:{chain.id}:{turn.position}")
    else:
        chain.status = "completed"
        for participant in s.scalars(select(Participant).where(Participant.chain_id == chain.id)):
            notify(s, participant.user_id, chain.id, "The finale is here. Your completed story is ready.")
    return True


def submit(s, chain_id, turn_id, user_id, text, assisted, timestamp=None):
    chain = lock_chain(s, chain_id)
    require_member(s, chain_id, user_id)
    turn = s.scalar(select(Turn).where(Turn.id == turn_id, Turn.chain_id == chain_id).with_for_update())
    if not turn:
        fail("Turn not found", 404)
    if turn.user_id != user_id:
        fail("It’s another participant’s turn", 403)
    if turn.status == "submitted":
        fail("This turn is already complete")
    timestamp = timestamp or now()
    if timestamp >= utc(turn.deadline_at):
        fail("The deadline has passed; the prepared fallback will complete this turn")
    if assisted and not turn.suggestions:
        fail("Suggestions are still being prepared", 422)
    complete_turn(s, chain, turn, text, assisted=assisted, timestamp=timestamp)


def timeout(s, turn_id, timestamp=None):
    turn = s.get(Turn, turn_id)
    if not turn:
        return
    chain = lock_chain(s, turn.chain_id)
    s.refresh(turn, with_for_update=True)
    timestamp = timestamp or now()
    if turn.status == "submitted" or utc(turn.deadline_at) > timestamp:
        return
    if turn.suggestions is None:
        turn.status = "generating"
        return
    fallback = turn.suggestions[turn.fallback_index]
    complete_turn(s, chain, turn, fallback, generated=True, timestamp=timestamp)


def publication(s, chain_id, user_id, decision, timestamp=None):
    chain = lock_chain(s, chain_id)
    require_member(s, chain_id, user_id)
    if chain.status != "completed":
        fail("Finish the story before requesting publication")
    if chain.publication_status in {"approved", "rejected"}:
        fail("Publication decisions are final for this story")
    timestamp = timestamp or now()
    if decision == "request":
        if chain.publication_status != "not_requested":
            fail("Publication has already been requested")
        chain.publication_status = "awaiting_approvals"
        chain.publication_requester_id = user_id
        chain.publication_requested_at = timestamp
        decision = "approved"
        for participant in s.scalars(select(Participant).where(Participant.chain_id == chain_id)):
            notify(
                s, participant.user_id, chain_id, "Publication requested. Everyone must explicitly approve."
            )
    elif chain.publication_status != "awaiting_approvals":
        fail("Publication has not been requested")
    approval = s.get(Approval, (chain_id, user_id))
    if approval.decision != "pending":
        fail("Your publication decision is already recorded")
    approval.decision = decision
    approval.decided_at = timestamp
    s.flush()
    if decision == "rejected":
        chain.publication_status = "rejected"
    else:
        missing = s.scalar(
            select(func.count())
            .select_from(Approval)
            .where(Approval.chain_id == chain_id, Approval.decision != "approved")
        )
        if missing == 0:
            chain.publication_status = "approved"
            chain.visibility = "published"
            chain.published_at = timestamp
