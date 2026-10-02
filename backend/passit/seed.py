from itertools import combinations

from sqlalchemy import select

from .models import (
    AIAssignment,
    AIProfile,
    AnalyticsState,
    Friendship,
    Group,
    GroupMember,
    Motive,
    PlatformSettings,
    User,
    UserSettings,
)

MOTIVES = [
    ("worse", "Make it worse", "💀"),
    ("twist", "Add a plot twist", "🤯"),
    ("awkward", "Make it awkward", "😂"),
    ("absurd", "Make it absurd", "🌀"),
    ("wholesome", "Make it wholesome", "❤️"),
    ("ruin", "Ruin the situation", "😈"),
    ("save", "Save the situation", "🦸"),
    ("character", "Introduce a new character", "👤"),
    ("end", "End the story", "🎬"),
]


def initialize(db, demo=False):
    with db.transaction() as s:
        if not s.get(AnalyticsState, 1):
            s.add(AnalyticsState(id=1))
        if not s.get(PlatformSettings, 1):
            s.add(PlatformSettings(id=1, max_participants_per_chain=20))
        for mid, label, emoji in MOTIVES:
            if not s.get(Motive, mid):
                s.add(Motive(id=mid, label=label, emoji=emoji))
        if demo and not s.scalar(select(User).where(User.issuer == "demo")):
            users = [
                User(issuer="demo", subject=name.lower(), name=name, color=color, admin=i == 0)
                for i, (name, color) in enumerate(
                    [
                        ("Alex", "#f3b949"),
                        ("Sam", "#a78bfa"),
                        ("Jamie", "#6ecbb3"),
                        ("Morgan", "#f08fa6"),
                        ("Riley", "#7fb8e8"),
                    ]
                )
            ]
            s.add_all(users)
            s.flush()
            for user in users:
                # Demo users deliberately opt in; real accounts always start opted out.
                s.add(UserSettings(user_id=user.id, allow_random_participation=True))
            for a, b in combinations(users, 2):
                left, right = sorted([a.id, b.id])
                s.add(Friendship(left_id=left, right_id=right, status="accepted", requested_by=a.id))
            group = Group(owner_id=users[0].id, name="The usual suspects")
            s.add(group)
            s.flush()
            s.add_all([GroupMember(group_id=group.id, user_id=u.id) for u in users[:4]])
        if demo and not s.get(AIAssignment, "default"):
            profile = AIProfile(
                revision=1, status="active", provider="demo", model_reference="offline-demo-v1"
            )
            s.add(profile)
            s.flush()
            s.add(AIAssignment(task="default", profile_id=profile.id))
