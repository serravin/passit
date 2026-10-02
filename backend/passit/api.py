import secrets
from contextlib import asynccontextmanager
from datetime import date as calendar_date
from datetime import timedelta
from typing import Annotated
from urllib.parse import urlsplit

import jwt
from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import aliased

from .ai import CreativeAI
from .analytics import report
from .auth import (
    check_access,
    digest,
    is_admin,
    optional_user,
    require_account_identity,
    require_admin,
    require_user,
)
from .config import Settings
from .db import Database
from .domain import (
    fail,
    friends,
    invalidate_prepared_text,
    launch,
    publication,
    require_member,
    submit,
    utc,
    validate_group,
)
from .guardrail import Guardrail, UnsafeAIOutput, ai_origin, content_hash, story_context
from .models import (
    AccountNotice,
    AIAssignment,
    AIProfile,
    Chain,
    Friendship,
    GeneratedTextProof,
    Group,
    GroupMember,
    Like,
    LoginSession,
    Motive,
    Notification,
    Participant,
    PlatformSettings,
    SafetyReview,
    Turn,
    User,
    UserModerationEvent,
    UserSettings,
    WorkItem,
    now,
)
from .moderation import set_block
from .schemas import (
    ActivateProfile,
    Decision,
    FriendInput,
    FriendResponse,
    GroupInput,
    Launch,
    PlatformInput,
    Preferences,
    ProfileInput,
    SafetyDecision,
    SetupRequest,
    Submission,
    UserBlockInput,
)
from .seed import initialize
from .telemetry import measured_generate
from .views import chain_view, date, user_view

CurrentUser = Annotated[User, Depends(require_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]
Admin = Annotated[User, Depends(require_admin)]
AccountIdentity = Annotated[User, Depends(require_account_identity)]


def create_app(settings=None, db=None):
    settings = settings or Settings()
    settings.validate()
    db = db or Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        if settings.mode == "demo":
            db.create_schema()
            initialize(db, demo=True)
        yield

    app = FastAPI(title="PassIt", version="0.1.0", lifespan=lifespan)
    app.state.settings, app.state.db = settings, db
    app.state.guardrail = Guardrail(db, settings)
    if settings.mode == "production":
        app.state.jwks = jwt.PyJWKClient(settings.jwks_url)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def protections(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            # Cookie-based demo commands require an allowed Origin; login also rejects cross-site requests.
            if (origin and origin not in settings.allowed_origins) or (
                request.cookies.get("passit_session") and not origin
            ):
                return JSONResponse({"detail": "Untrusted request origin"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/health")
    def health():
        with db.sessions() as s:
            s.execute(select(1))
        return {"status": "ok", "mode": settings.mode}

    @app.get("/api/config")
    def config():
        with db.sessions() as s:
            platform = s.get(PlatformSettings, 1)
            return {
                "mode": settings.mode,
                "global_max_participants": platform.max_participants_per_chain,
                "motives": [
                    {"id": m.id, "label": m.label, "emoji": m.emoji} for m in s.scalars(select(Motive))
                ],
            }

    @app.get("/api/demo/accounts")
    def accounts():
        if settings.mode != "demo":
            fail("Not found", 404)
        with db.sessions() as s:
            return [
                user_view(u) for u in s.scalars(select(User).where(User.issuer == "demo").order_by(User.name))
            ]

    @app.post("/api/demo/login")
    def login(data: FriendInput, response: Response):
        if settings.mode != "demo":
            fail("Not found", 404)
        with db.transaction() as s:
            user = s.get(User, data.user_id)
            if not user or user.issuer != "demo":
                fail("Account not found", 404)
            check_access(user)
            token = secrets.token_urlsafe(32)
            s.add(
                LoginSession(token_hash=digest(token), user_id=user.id, expires_at=now() + timedelta(days=1))
            )
            response.set_cookie(
                "passit_session",
                token,
                httponly=True,
                samesite="lax",
                max_age=86400,
                secure=settings.origin.startswith("https://"),
            )
            return user_view(user)

    @app.post("/api/logout")
    def logout(request: Request, response: Response):
        token = request.cookies.get("passit_session")
        if token:
            with db.transaction() as s:
                row = s.get(LoginSession, digest(token))
                if row:
                    s.delete(row)
        response.delete_cookie("passit_session")
        return {"ok": True}

    @app.get("/api/me")
    def me(user: CurrentUser):
        with db.sessions() as s:
            preferences = s.get(UserSettings, user.id)
            return {
                **user_view(user),
                "admin": user.admin,
                "settings": {
                    "allow_random_participation": preferences.allow_random_participation,
                    "notifications_enabled": preferences.notifications_enabled,
                    "language": preferences.language,
                },
            }

    @app.get("/api/account-status")
    def account_status(user: AccountIdentity):
        with db.sessions() as s:
            return {
                "user_id": user.id,
                "blocked_at": date(user.blocked_at),
                "notices": [
                    {
                        "id": n.id,
                        "kind": n.kind,
                        "source": n.source,
                        "categories": n.categories,
                        "created_at": date(n.created_at),
                    }
                    for n in s.scalars(
                        select(AccountNotice)
                        .where(AccountNotice.user_id == user.id, AccountNotice.read.is_(False))
                        .order_by(AccountNotice.created_at.desc())
                        .limit(20)
                    )
                ],
            }

    @app.post("/api/account-notices/{notice_id}/read")
    def read_account_notice(notice_id: str, user: AccountIdentity):
        with db.transaction() as s:
            notice = s.get(AccountNotice, notice_id, with_for_update=True)
            if not notice or notice.user_id != user.id:
                fail("Notice not found", 404)
            notice.read = True
        return {"ok": True}

    @app.put("/api/me/settings")
    def preferences(data: Preferences, user: CurrentUser):
        with db.transaction() as s:
            row = s.get(UserSettings, user.id)
            for key, value in data.model_dump().items():
                setattr(row, key, value)
        return data

    @app.get("/api/friends")
    def friend_list(user: CurrentUser):
        with db.sessions() as s:
            accepted = friends(s, user.id)
            pending = list(
                s.scalars(
                    select(Friendship).where(
                        or_(Friendship.left_id == user.id, Friendship.right_id == user.id),
                        Friendship.status == "pending",
                    )
                )
            )
            return {
                "friends": [user_view(s.get(User, uid)) for uid in sorted(accepted)],
                "requests": [
                    {
                        **user_view(s.get(User, f.right_id if f.left_id == user.id else f.left_id)),
                        "incoming": f.requested_by != user.id,
                    }
                    for f in pending
                ],
            }

    @app.get("/api/users")
    def user_search(user: CurrentUser, q: str = Query(min_length=2, max_length=80)):
        with db.sessions() as s:
            return [
                user_view(u)
                for u in s.scalars(
                    select(User)
                    .where(User.name.ilike(f"%{q}%"), User.id != user.id, User.blocked_at.is_(None))
                    .limit(20)
                )
            ]

    @app.post("/api/friends")
    def request_friend(data: FriendInput, user: CurrentUser):
        with db.transaction() as s:
            target = s.get(User, data.user_id)
            if data.user_id == user.id or not target or target.blocked_at is not None:
                fail("Choose another user", 422)
            left, right = sorted([user.id, data.user_id])
            if s.get(Friendship, (left, right)):
                fail("A friendship or request already exists")
            s.add(Friendship(left_id=left, right_id=right, requested_by=user.id))
        return {"ok": True}

    @app.post("/api/friends/{other_id}/respond")
    def respond_friend(other_id: str, data: FriendResponse, user: CurrentUser):
        with db.transaction() as s:
            left, right = sorted([user.id, other_id])
            row = s.get(Friendship, (left, right), with_for_update=True)
            if not row or row.status != "pending" or row.requested_by == user.id:
                fail("Incoming request not found", 404)
            if data.accept:
                if s.get(User, other_id).blocked_at is not None:
                    fail("Choose another user", 422)
                row.status = "accepted"
            else:
                s.delete(row)
        return {"ok": True}

    @app.delete("/api/friends/{other_id}")
    def remove_friend(other_id: str, user: CurrentUser):
        with db.transaction() as s:
            row = s.get(Friendship, tuple(sorted([user.id, other_id])))
            if row:
                s.delete(row)
        return {"ok": True}

    def group_view(s, group):
        return {
            "id": group.id,
            "name": group.name,
            "owner_id": group.owner_id,
            "members": [
                user_view(s.get(User, m.user_id))
                for m in s.scalars(select(GroupMember).where(GroupMember.group_id == group.id))
            ],
        }

    @app.get("/api/groups")
    def groups(user: CurrentUser):
        with db.sessions() as s:
            return [
                group_view(s, g)
                for g in s.scalars(select(Group).join(GroupMember).where(GroupMember.user_id == user.id))
            ]

    @app.post("/api/groups")
    def create_group(data: GroupInput, user: CurrentUser):
        with db.transaction() as s:
            members = validate_group(s, user.id, data.member_ids)
            group = Group(name=data.name, owner_id=user.id)
            s.add(group)
            s.flush()
            s.add_all([GroupMember(group_id=group.id, user_id=uid) for uid in members])
            s.flush()
            return group_view(s, group)

    @app.put("/api/groups/{group_id}")
    def edit_group(group_id: str, data: GroupInput, user: CurrentUser):
        with db.transaction() as s:
            group = s.get(Group, group_id, with_for_update=True)
            if not group or group.owner_id != user.id:
                fail("Owned group not found", 404)
            members = validate_group(s, user.id, data.member_ids)
            group.name = data.name
            existing = list(s.scalars(select(GroupMember).where(GroupMember.group_id == group_id)))
            present = {m.user_id for m in existing}
            for member in existing:
                if member.user_id not in members:
                    s.delete(member)
            for uid in members - present:
                s.add(GroupMember(group_id=group_id, user_id=uid))
            s.flush()
            return group_view(s, group)

    @app.delete("/api/groups/{group_id}/membership")
    def leave_group(group_id: str, user: CurrentUser):
        with db.transaction() as s:
            group = s.get(Group, group_id, with_for_update=True)
            member = s.get(GroupMember, (group_id, user.id))
            if not group or not member:
                fail("Group not found", 404)
            if group.owner_id == user.id:
                fail("The owner stays in their group; remove other members using Edit")
            s.delete(member)
        return {"ok": True}

    @app.get("/api/chains")
    def my_chains(user: CurrentUser):
        with db.sessions() as s:
            return [
                chain_view(s, c, user.id)
                for c in s.scalars(
                    select(Chain)
                    .join(Participant)
                    .where(Participant.user_id == user.id)
                    .where(Chain.safety_status != "flagged")
                    .order_by(Chain.created_at.desc())
                    .limit(100)
                )
            ]

    @app.post("/api/chains", status_code=201)
    def new_chain(data: Launch, user: CurrentUser):
        with db.sessions() as s:
            origin = "ai" if ai_origin(s, user.id, data.setup, "setup") else "human"
        review = app.state.guardrail.check(data.setup, user_id=user.id, origin=origin)
        app.state.guardrail.enforce(review)
        if data.rules:
            rule_review = app.state.guardrail.check(
                data.rules, user_id=user.id, kind="rules", context={"setup": data.setup}
            )
            app.state.guardrail.enforce(rule_review)
        with db.transaction() as s:
            s.get(PlatformSettings, 1, with_for_update=True)
            assignment = s.get(AIAssignment, "guardrail")
            if not assignment or assignment.profile_id != review.profile_id:
                fail("Safety check unavailable. Please try again.", 503)
            if data.rules and rule_review.profile_id != assignment.profile_id:
                fail("Safety check unavailable. Please try again.", 503)
            check_access(s.get(User, user.id))
            chain = launch(s, user, data)
            chain.safety_origin = origin
            return chain_view(s, chain, user.id, detail=True)

    @app.get("/api/chains/{chain_id}")
    def get_chain(chain_id: str, user: OptionalUser):
        with db.sessions() as s:
            chain = require_member(s, chain_id, user.id if user else None, allow_published=True)
            return chain_view(s, chain, user.id if user else None, detail=True)

    @app.post("/api/chains/{chain_id}/turns/{turn_id}/submit")
    def submit_turn(chain_id: str, turn_id: str, data: Submission, user: CurrentUser):
        with db.sessions() as s:
            chain = require_member(s, chain_id, user.id)
            turn = s.get(Turn, turn_id)
            if not turn or turn.chain_id != chain_id:
                fail("Turn not found", 404)
            if turn.user_id != user.id:
                fail("It’s another participant’s turn", 403)
            if turn.status == "submitted":
                fail("This turn is already complete")
            if utc(turn.deadline_at) <= now():
                fail("The deadline has passed; the prepared fallback will complete this turn")
            context = story_context(s, chain)
            origin = (
                "ai"
                if data.text in (turn.suggestions or [])
                or ai_origin(s, user.id, data.text, "suggestion", turn_id)
                else "human"
            )
        review = app.state.guardrail.check(
            data.text,
            context=context,
            kind="contribution",
            origin=origin,
            user_id=user.id,
            chain_id=chain_id,
            turn_id=turn_id,
        )
        app.state.guardrail.enforce(review)
        with db.transaction() as s:
            s.get(PlatformSettings, 1, with_for_update=True)
            assignment = s.get(AIAssignment, "guardrail")
            if not assignment or assignment.profile_id != review.profile_id:
                fail("Safety check unavailable. Please try again.", 503)
            check_access(s.get(User, user.id))
            submit(s, chain_id, turn_id, user.id, data.text, data.ai_assisted)
            s.get(Turn, turn_id).safety_origin = origin
            return chain_view(s, s.get(Chain, chain_id), user.id, detail=True)

    @app.post("/api/chains/{chain_id}/publication")
    def publish(chain_id: str, data: Decision, user: CurrentUser):
        with db.sessions() as s:
            chain = require_member(s, chain_id, user.id)
            if chain.status != "completed":
                fail("Finish the story before requesting publication")
        if data.decision != "rejected" and not app.state.guardrail.scan_chain(chain_id):
            fail("The story was withheld by the safety check. An administrator can review it.", 422)
        with db.transaction() as s:
            s.get(PlatformSettings, 1, with_for_update=True)
            if data.decision != "rejected" and s.get(Chain, chain_id).safety_status != "approved":
                fail("The story is waiting for its safety check. Please try again.", 503)
            check_access(s.get(User, user.id))
            publication(s, chain_id, user.id, data.decision)
            return chain_view(s, s.get(Chain, chain_id), user.id, detail=True)

    @app.get("/api/discover")
    def discover(user: OptionalUser, category: str = "trending", offset: int = Query(default=0, ge=0)):
        if category not in {"trending", "new", "awkward", "absurd", "twist"}:
            fail("Unknown discovery category", 422)
        with db.sessions() as s:
            query = select(Chain).where(
                Chain.status == "completed",
                Chain.visibility == "published",
                Chain.publication_status == "approved",
                Chain.safety_status == "approved",
            )
            if category in {"awkward", "absurd", "twist"}:
                query = query.where(Chain.id.in_(select(Turn.chain_id).where(Turn.motive_id == category)))
            if category == "trending":
                count = (
                    select(func.count())
                    .select_from(Like)
                    .where(Like.chain_id == Chain.id)
                    .correlate(Chain)
                    .scalar_subquery()
                )
                query = query.order_by(count.desc(), Chain.published_at.desc())
            else:
                query = query.order_by(Chain.published_at.desc())
            return [
                chain_view(s, c, user.id if user else None) for c in s.scalars(query.offset(offset).limit(30))
            ]

    def change_like(s, target, target_id, user, add):
        if target == "chains":
            require_member(s, target_id, user.id, allow_published=True)
            field, kw = Like.chain_id, {"chain_id": target_id}
        elif target == "turns":
            turn = s.get(Turn, target_id)
            if not turn:
                fail("Turn not found", 404)
            require_member(s, turn.chain_id, user.id, allow_published=True)
            if turn.status != "submitted":
                fail("Only completed contributions can be liked", 422)
            field, kw = Like.turn_id, {"turn_id": target_id}
        else:
            fail("Not found", 404)
        # Chain lock serializes insert/remove races across independent target likes.
        chain_id = target_id if target == "chains" else turn.chain_id
        s.get(Chain, chain_id, with_for_update=True)
        existing = s.scalar(select(Like).where(field == target_id, Like.user_id == user.id))
        if add and not existing:
            s.add(Like(user_id=user.id, **kw))
        elif not add and existing:
            s.delete(existing)
        return {"ok": True}

    @app.put("/api/likes/{target}/{target_id}")
    def add_like(target: str, target_id: str, user: CurrentUser):
        with db.transaction() as s:
            return change_like(s, target, target_id, user, True)

    @app.delete("/api/likes/{target}/{target_id}")
    def remove_like(target: str, target_id: str, user: CurrentUser):
        with db.transaction() as s:
            return change_like(s, target, target_id, user, False)

    @app.get("/api/notifications")
    def notifications(user: CurrentUser):
        with db.sessions() as s:
            return [
                {
                    "id": n.id,
                    "chain_id": n.chain_id,
                    "message": n.message,
                    "read": n.read,
                    "created_at": date(n.created_at),
                }
                for n in s.scalars(
                    select(Notification)
                    .where(Notification.user_id == user.id)
                    .order_by(Notification.created_at.desc())
                    .limit(50)
                )
            ]

    @app.post("/api/notifications/read")
    def read_notifications(user: CurrentUser):
        with db.transaction() as s:
            for notification in s.scalars(
                select(Notification).where(Notification.user_id == user.id, Notification.read.is_(False))
            ):
                notification.read = True
        return {"ok": True}

    @app.post("/api/setup-assistance")
    def assist_setup(data: SetupRequest, user: CurrentUser):
        with db.sessions() as s:
            assignment = s.get(AIAssignment, "setup") or s.get(AIAssignment, "default")
            if not assignment:
                fail("AI is not configured", 503)
            profile = s.get(AIProfile, assignment.profile_id)
            try:
                result = measured_generate(db, CreativeAI(settings), profile, "setup", {"theme": data.theme})
            except Exception:
                fail("Setup assistance is unavailable; you can write your own setup", 503)
        try:
            review = app.state.guardrail.check_generated(
                result["setup"], kind="generated_setup", user_id=user.id
            )
        except UnsafeAIOutput:
            fail("The generated setup was withheld by the safety check. Please try again.", 503)
        with db.transaction() as s:
            s.get(PlatformSettings, 1, with_for_update=True)
            assignment = s.get(AIAssignment, "guardrail")
            if not assignment or assignment.profile_id != review.profile_id:
                fail("Safety check unavailable. Please try again.", 503)
            check_access(s.get(User, user.id))
            s.add(
                GeneratedTextProof(user_id=user.id, kind="setup", content_hash=content_hash(result["setup"]))
            )
        return result

    @app.get("/api/admin/statistics")
    def statistics(
        user: Admin,
        preset: str = Query(default="mtd", max_length=30),
        start: calendar_date | None = None,
        end: calendar_date | None = None,
        timezone: str = Query(default="UTC", max_length=100),
    ):
        with db.sessions() as s:
            result = report(s, preset=preset, start_date=start, end_date=end, timezone=timezone)
            return {**result, "mode": settings.mode}

    @app.get("/api/admin")
    def admin_state(user: Admin):
        with db.sessions() as s:
            profiles = [
                {
                    "id": p.id,
                    "revision": p.revision,
                    "status": p.status,
                    "validated_at": date(p.validated_at),
                    **{k: getattr(p, k) for k in ProfileInput.model_fields},
                }
                for p in s.scalars(select(AIProfile).order_by(AIProfile.revision.desc()))
            ]
            work = [
                {
                    "id": w.id,
                    "task": w.task,
                    "attempts": w.attempts,
                    "error_code": w.error_code,
                    "status": w.status,
                }
                for w in s.scalars(select(WorkItem).where(WorkItem.status == "failed").limit(100))
            ]
            return {
                "max_participants_per_chain": s.get(PlatformSettings, 1).max_participants_per_chain,
                "profiles": profiles,
                "assignments": {a.task: a.profile_id for a in s.scalars(select(AIAssignment))},
                "failed_work": work,
            }

    def admin_user_view(user):
        return {
            **user_view(user),
            "admin": is_admin(user, settings),
            "blocked_at": date(user.blocked_at),
            "block_reason": user.block_reason,
        }

    @app.get("/api/admin/users")
    def admin_users(
        user: Admin,
        q: str = Query(default="", max_length=80),
        status: str = Query(default="all", pattern="^(all|active|blocked)$"),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=25, ge=1, le=100),
    ):
        query = select(User)
        if q.strip():
            query = query.where(or_(User.name.icontains(q.strip(), autoescape=True), User.id == q.strip()))
        if status != "all":
            query = query.where(
                User.blocked_at.is_(None) if status == "active" else User.blocked_at.is_not(None)
            )
        with db.sessions() as s:
            return {
                "items": [
                    admin_user_view(u)
                    for u in s.scalars(query.order_by(User.name, User.id).offset(offset).limit(limit))
                ],
                "total": s.scalar(select(func.count()).select_from(query.subquery())),
                "offset": offset,
                "limit": limit,
            }

    @app.put("/api/admin/users/{user_id}/block")
    def block_user(user_id: str, data: UserBlockInput, user: Admin):
        with db.transaction() as s:
            # Serialize with launches so a completed block cannot enter a new cast.
            s.get(PlatformSettings, 1, with_for_update=True)
            target = s.get(User, user_id, with_for_update=True)
            if not target:
                fail("Account not found", 404)
            if data.blocked and (target.id == user.id or is_admin(target, settings)):
                fail("Administrator accounts cannot be blocked", 422)
            if (target.blocked_at is not None) != data.blocked:
                set_block(s, target, data.blocked, admin_id=user.id, reason=data.reason or None)
                s.flush()
            return admin_user_view(target)

    @app.get("/api/admin/moderation")
    def moderation_history(user: Admin, limit: int = Query(default=20, ge=1, le=100)):
        target, actor = aliased(User), aliased(User)
        with db.sessions() as s:
            return [
                {
                    "id": event.id,
                    "user": user_view(account),
                    "admin": user_view(administrator) if administrator else None,
                    "source": event.source,
                    "blocked": event.blocked,
                    "reason": event.reason,
                    "created_at": date(event.created_at),
                }
                for event, account, administrator in s.execute(
                    select(UserModerationEvent, target, actor)
                    .join(target, target.id == UserModerationEvent.user_id)
                    .outerjoin(actor, actor.id == UserModerationEvent.admin_id)
                    .order_by(UserModerationEvent.created_at.desc(), UserModerationEvent.id.desc())
                    .limit(limit)
                )
            ]

    @app.get("/api/admin/safety-reviews")
    def safety_reviews(
        user: Admin,
        status: str = Query(default="pending", pattern="^(pending|allowed|confirmed)$"),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=25, ge=1, le=100),
    ):
        query = select(SafetyReview).where(
            SafetyReview.allowed.is_(False), SafetyReview.review_status == status
        )
        with db.sessions() as s:
            return {
                "items": [
                    {
                        "id": r.id,
                        "user": user_view(s.get(User, r.user_id)) if r.user_id else None,
                        "chain_id": r.chain_id,
                        "kind": r.kind,
                        "origin": r.origin,
                        "categories": r.categories,
                        "text": r.text,
                        "context": r.context,
                        "created_at": date(r.created_at),
                        "review_status": r.review_status,
                        "profile_id": r.profile_id,
                    }
                    for r in s.scalars(
                        query.order_by(SafetyReview.created_at.desc()).offset(offset).limit(limit)
                    )
                ],
                "total": s.scalar(select(func.count()).select_from(query.subquery())),
                "offset": offset,
                "limit": limit,
            }

    @app.put("/api/admin/safety-reviews/{review_id}")
    def decide_safety(review_id: str, data: SafetyDecision, user: Admin):
        return app.state.guardrail.decide(review_id, data.decision, user.id)

    @app.put("/api/admin/platform")
    def update_platform(data: PlatformInput, user: Admin):
        with db.transaction() as s:
            s.get(
                PlatformSettings, 1, with_for_update=True
            ).max_participants_per_chain = data.max_participants_per_chain
        return data

    @app.post("/api/admin/profiles", status_code=201)
    def create_profile(data: ProfileInput, user: Admin):
        if data.provider == "demo" and settings.mode != "demo":
            fail("Demo profiles cannot be used in production", 422)
        if data.provider == "azure_openai":
            endpoint = urlsplit(data.endpoint)
            if (
                endpoint.scheme != "https"
                or endpoint.hostname not in settings.ai_allowed_hosts
                or not data.deployment_name
            ):
                fail("Use an approved AI endpoint and deployment", 422)
        with db.transaction() as s:
            s.get(PlatformSettings, 1, with_for_update=True)
            revision = (s.scalar(select(func.max(AIProfile.revision))) or 0) + 1
            profile = AIProfile(revision=revision, updated_by=user.id, **data.model_dump())
            s.add(profile)
            s.flush()
            return {"id": profile.id, "revision": profile.revision, "status": profile.status}

    @app.post("/api/admin/profiles/{profile_id}/validate")
    def validate_profile(profile_id: str, user: Admin):
        with db.sessions() as s:
            profile = s.get(AIProfile, profile_id)
            if not profile:
                fail("Profile not found", 404)
            context = {
                "setup": "The office printer declared itself mayor.",
                "story": ["The office printer declared itself mayor."],
                "used_motives": [],
                "remaining": 2,
                "rules": "",
                "eligible_motives": ["worse", "awkward"],
                "motive_id": "awkward",
            }
            try:
                adapter = CreativeAI(settings)
                for task in ("handoff", "suggestions", "title", "setup", "guardrail"):
                    validation_context = (
                        {
                            "candidate": "A pigeon audited the coffee machine.",
                            "story_context": {},
                            "kind": "setup",
                        }
                        if task == "guardrail"
                        else context
                    )
                    result = measured_generate(
                        db, adapter, profile, task, validation_context, purpose="validation"
                    )
                    if task == "guardrail" and not result["allowed"]:
                        raise ValueError("Guardrail rejected harmless validation text")
                negative = {
                    "candidate": "[[demo:bullying]]"
                    if profile.provider == "demo"
                    else "Everyone should harass Alex every day until Alex quits this group. Alex is worthless and deserves it.",
                    "story_context": {},
                    "kind": "contribution",
                }
                result = measured_generate(db, adapter, profile, "guardrail", negative, purpose="validation")
                if result["allowed"]:
                    raise ValueError("Guardrail missed validation abuse")
            except Exception as exc:
                fail(
                    f"AI validation failed ({type(exc).__name__}); check connectivity and model parameters",
                    422,
                )
        with db.transaction() as s:
            s.get(AIProfile, profile_id).validated_at = now()
        return {"validated": True}

    @app.post("/api/admin/profiles/{profile_id}/activate")
    def activate_profile(profile_id: str, data: ActivateProfile, user: Admin):
        with db.transaction() as s:
            s.get(PlatformSettings, 1, with_for_update=True)
            profile = s.get(AIProfile, profile_id)
            if not profile or not profile.validated_at:
                fail("Validate the profile before activation", 422)
            assignment = s.get(AIAssignment, data.task)
            if data.task == "guardrail" and (not assignment or assignment.profile_id != profile_id):
                s.execute(
                    update(Chain).where(Chain.safety_status == "approved").values(safety_status="pending")
                )
                invalidate_prepared_text(s)
            if assignment:
                assignment.profile_id = profile_id
            else:
                s.add(AIAssignment(task=data.task, profile_id=profile_id))
            profile.status = "active"
            profile.updated_by = user.id
        return {"ok": True}

    @app.post("/api/admin/work/{item_id}/retry")
    def retry_work(item_id: str, user: Admin):
        with db.transaction() as s:
            item = s.get(WorkItem, item_id, with_for_update=True)
            if not item or item.status != "failed":
                fail("Failed work item not found", 404)
            item.status, item.attempts, item.available_at = "pending", 0, now()
        return {"ok": True}

    return app


app = create_app()
