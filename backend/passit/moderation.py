"""Account changes and public notices; administrator reasons remain private."""

from .models import AccountNotice, UserModerationEvent, now


def set_block(
    s, user, blocked, *, admin_id=None, reason=None, source="admin", review_id=None, categories=None
):
    if (user.blocked_at is not None) == blocked:
        return False
    timestamp = now()
    user.blocked_at = timestamp if blocked else None
    user.block_reason = reason if blocked else None
    user.guardrail_block_id = review_id if blocked else None
    s.add(
        UserModerationEvent(
            user_id=user.id,
            admin_id=admin_id,
            blocked=blocked,
            reason=reason,
            source=source,
            created_at=timestamp,
        )
    )
    s.add(
        AccountNotice(
            user_id=user.id,
            kind="blocked" if blocked else "restored",
            source=source,
            categories=categories or [],
            created_at=timestamp,
        )
    )
    return True
