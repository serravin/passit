from sqlalchemy import func, select

from .domain import utc
from .models import Approval, Like, Motive, Participant, Turn, User, now


def date(value):
    return utc(value).isoformat() if value else None


def user_view(user):
    return {"id": user.id, "name": user.name, "color": user.color}


def like_view(s, field, target_id, viewer):
    likes = s.scalar(select(func.count()).select_from(Like).where(field == target_id))
    mine = bool(viewer and s.scalar(select(Like.id).where(field == target_id, Like.user_id == viewer)))
    return {"likes": likes, "liked": mine}


def chain_view(s, chain, viewer, detail=False):
    participants = list(s.scalars(select(Participant).where(Participant.chain_id == chain.id)))
    turns = list(s.scalars(select(Turn).where(Turn.chain_id == chain.id).order_by(Turn.position)))
    active = next((t for t in turns if t.status != "submitted"), None)
    result = {
        "id": chain.id, "title": chain.title or "Untitled Chain", "setup": chain.setup,
        "rules": chain.rules, "creator_id": chain.creator_id, "status": chain.status,
        "visibility": chain.visibility, "publication_status": chain.publication_status,
        "group_mode": chain.group_mode, "source_group_id": chain.source_group_id,
        "created_at": date(chain.created_at), "published_at": date(chain.published_at),
        "turn_timeout_seconds": chain.turn_timeout_seconds,
        "min_participants": chain.min_participants, "max_participants": chain.max_participants,
        "participant_count": len(participants), "completed_contributions": sum(p.contributed for p in participants),
        "pass_count": len(turns), "is_participant": any(p.user_id == viewer for p in participants),
        "your_turn": bool(active and active.user_id == viewer and utc(active.deadline_at) > now()),
        "motive_ids": [t.motive_id for t in turns],
        **like_view(s, Like.chain_id, chain.id, viewer),
    }
    if detail:
        result["server_time"] = date(now())
        result["participants"] = [{**user_view(s.get(User, p.user_id)), "contributed": p.contributed}
                                  for p in participants]
        result["creator"] = user_view(s.get(User, chain.creator_id))
        result["approvals"] = [{"user_id": a.user_id, "decision": a.decision} for a in s.scalars(
            select(Approval).where(Approval.chain_id == chain.id))] if result["is_participant"] else []
        result["turns"] = []
        for turn in turns:
            motive = s.get(Motive, turn.motive_id)
            entry = {
                "id": turn.id, "position": turn.position, "user": user_view(s.get(User, turn.user_id)),
                "motive": {"id": motive.id, "label": motive.label, "emoji": motive.emoji},
                "status": turn.status, "text": turn.text, "assigned_at": date(turn.assigned_at),
                "deadline_at": date(turn.deadline_at), "submitted_at": date(turn.submitted_at),
                "ai_assisted": turn.ai_assisted, "ai_generated": turn.ai_generated,
                **like_view(s, Like.turn_id, turn.id, viewer),
            }
            if turn.user_id == viewer and turn.status != "submitted":
                entry["suggestions"] = turn.suggestions
            result["turns"].append(entry)
    return result
