"""Server-side safety checks. Reject content and persist blocks before raising HTTP errors."""

import hashlib
import json

from sqlalchemy import select

from .ai import CreativeAI, validate_output
from .auth import check_access, is_admin
from .domain import fail
from .models import (
    AIAssignment,
    AIProfile,
    Chain,
    GeneratedTextProof,
    PlatformSettings,
    SafetyReview,
    Turn,
    User,
    now,
)
from .moderation import set_block
from .telemetry import measured_generate


class UnsafeAIOutput(ValueError):
    pass


def allowed(review):
    return review.allowed or review.review_status == "allowed"


def content_hash(text):
    return hashlib.sha256(text.strip().encode()).hexdigest()


def ai_origin(s, user_id, text, kind, turn_id=None):
    return bool(
        s.scalar(
            select(GeneratedTextProof.id)
            .where(
                GeneratedTextProof.user_id == user_id,
                GeneratedTextProof.content_hash == content_hash(text),
                GeneratedTextProof.kind == kind,
                GeneratedTextProof.turn_id == turn_id,
            )
            .limit(1)
        )
    )


def story_context(s, chain):
    texts = list(
        s.scalars(
            select(Turn.text)
            .where(Turn.chain_id == chain.id, Turn.status == "submitted")
            .order_by(Turn.position)
        )
    )
    return {"setup": chain.setup, "rules": chain.rules, "previous_contributions": texts[-3:]}


class Guardrail:
    def __init__(self, db, settings, ai=None):
        self.db, self.settings = db, settings
        self.ai = ai or CreativeAI(settings)

    def check(
        self,
        candidate,
        *,
        context=None,
        kind="setup",
        origin="human",
        user_id=None,
        chain_id=None,
        turn_id=None,
        profile_id=None,
        work_item_id=None,
        persisted=False,
    ):
        context = context or {}
        with self.db.sessions() as s:
            assignment = s.get(AIAssignment, "guardrail")
            profile_id = profile_id or (assignment.profile_id if assignment else None)
            profile = s.get(AIProfile, profile_id) if profile_id else None
            if not profile:
                fail("An administrator must configure the guardrail before content can be accepted", 503)
            data = {"candidate": candidate, "story_context": context, "kind": kind, "policy_version": "v1"}
            key_data = {
                **data,
                "profile_id": profile.id,
                "origin": origin,
                "user_id": user_id,
                "chain_id": chain_id,
                "turn_id": turn_id,
            }
            key = hashlib.sha256(
                json.dumps(key_data, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            previous = s.scalar(select(SafetyReview).where(SafetyReview.key == key))
            if previous:
                return previous
            inherited = None
            if kind in {"setup", "rules"} and chain_id and user_id:
                for initial_origin in [origin, "human"] if origin == "ai" else [origin]:
                    initial = {**key_data, "chain_id": None, "origin": initial_origin}
                    initial_key = hashlib.sha256(
                        json.dumps(initial, sort_keys=True, ensure_ascii=False).encode()
                    ).hexdigest()
                    original = s.scalar(select(SafetyReview).where(SafetyReview.key == initial_key))
                    if original and allowed(original):
                        inherited = {"allowed": True, "categories": []}
                        break
        try:
            result = inherited or measured_generate(
                self.db,
                self.ai,
                profile,
                "guardrail",
                data,
                chain_id=chain_id,
                work_item_id=work_item_id,
                purpose="guardrail",
                operation_key=key,
            )
            result = validate_output("guardrail", result, data)
        except Exception:
            fail("Safety check unavailable. Please try again.", 503)
        with self.db.transaction() as s:
            s.get(PlatformSettings, 1, with_for_update=True)
            current = s.get(AIAssignment, "guardrail")
            if not current or current.profile_id != profile.id:
                fail("Safety check unavailable. Please try again.", 503)
            previous = s.scalar(select(SafetyReview).where(SafetyReview.key == key))
            if previous:
                return previous
            review = SafetyReview(
                key=key,
                profile_id=profile.id,
                user_id=user_id,
                chain_id=chain_id,
                turn_id=turn_id,
                kind=kind,
                origin=origin,
                allowed=result["allowed"],
                categories=result["categories"],
                text=None if result["allowed"] else candidate,
                context=None if result["allowed"] else context,
                review_status="allowed" if result["allowed"] else "pending",
            )
            s.add(review)
            s.flush()
            if not review.allowed:
                if chain_id and persisted:
                    s.get(Chain, chain_id, with_for_update=True).safety_status = "flagged"
                if origin == "human" and user_id:
                    user = s.get(User, user_id, with_for_update=True)
                    if not is_admin(user, self.settings):
                        set_block(
                            s,
                            user,
                            True,
                            reason="Guardrail flag: " + ", ".join(review.categories),
                            source="guardrail",
                            review_id=review.id,
                            categories=review.categories,
                        )
            return review

    def enforce(self, review):
        if allowed(review):
            return
        if review.origin == "human" and review.user_id:
            with self.db.transaction() as s:
                s.get(PlatformSettings, 1, with_for_update=True)
                user = s.get(User, review.user_id, with_for_update=True)
                if not is_admin(user, self.settings):
                    set_block(
                        s,
                        user,
                        True,
                        reason="Guardrail flag: " + ", ".join(review.categories),
                        source="guardrail",
                        review_id=review.id,
                        categories=review.categories,
                    )
            check_access(user)
        fail("Content was flagged by the safety check. An administrator can review it.", 422)

    def check_generated(self, candidate, **kwargs):
        review = self.check(candidate, origin="ai", **kwargs)
        if not allowed(review):
            raise UnsafeAIOutput("Generated content was withheld by the guardrail")
        return review

    def scan_chain(self, chain_id, *, profile_id=None, work_item_id=None):
        with self.db.sessions() as s:
            assignment = s.get(AIAssignment, "guardrail")
            profile_id = profile_id or (assignment.profile_id if assignment else None)
            if not profile_id:
                fail("An administrator must configure the guardrail before content can be accepted", 503)
            chain = s.get(Chain, chain_id)
            if not chain:
                return True
            turns = list(
                s.scalars(
                    select(Turn)
                    .where(Turn.chain_id == chain_id, Turn.status == "submitted")
                    .order_by(Turn.position)
                )
            )
            pieces = [
                (
                    chain.setup,
                    "setup",
                    chain.creator_id,
                    chain.safety_origin or ("ai" if chain.setup_ai_assisted else "human"),
                    None,
                    {},
                )
            ]
            if chain.rules:
                pieces.append((chain.rules, "rules", chain.creator_id, "human", None, {"setup": chain.setup}))
            previous = []
            for turn in turns:
                pieces.append(
                    (
                        turn.text,
                        "contribution",
                        turn.user_id,
                        turn.safety_origin or ("ai" if turn.ai_generated or turn.ai_assisted else "human"),
                        turn.id,
                        {"setup": chain.setup, "rules": chain.rules, "previous_contributions": previous[-3:]},
                    )
                )
                previous.append(turn.text)
            if chain.title:
                pieces.append((chain.title, "title", None, "ai", None, {"setup": chain.setup}))
            signature = (chain.setup, chain.rules, chain.title, tuple((t.id, t.text) for t in turns))
        safe = True
        for candidate, kind, user_id, origin, turn_id, context in pieces:
            review = self.check(
                candidate,
                context=context,
                kind=kind,
                user_id=user_id,
                origin=origin,
                turn_id=turn_id,
                chain_id=chain_id,
                profile_id=profile_id,
                work_item_id=work_item_id,
                persisted=True,
            )
            safe = allowed(review) and safe
        with self.db.transaction() as s:
            s.get(PlatformSettings, 1, with_for_update=True)
            chain = s.get(Chain, chain_id, with_for_update=True)
            current = list(
                s.scalars(
                    select(Turn)
                    .where(Turn.chain_id == chain_id, Turn.status == "submitted")
                    .order_by(Turn.position)
                )
            )
            assignment = s.get(AIAssignment, "guardrail")
            if (
                assignment
                and assignment.profile_id == profile_id
                and signature
                == (chain.setup, chain.rules, chain.title, tuple((t.id, t.text) for t in current))
            ):
                chain.safety_status = "approved" if safe else "flagged"
            else:
                safe = False
        return safe

    def decide(self, review_id, decision, admin_id):
        with self.db.transaction() as s:
            s.get(PlatformSettings, 1, with_for_update=True)
            review = s.get(SafetyReview, review_id, with_for_update=True)
            if not review or review.allowed:
                fail("Safety review not found", 404)
            status = "allowed" if decision == "allow" else "confirmed"
            if review.review_status != "pending" and review.review_status != status:
                fail("This review has already been decided")
            review.review_status, review.reviewer_id, review.reviewed_at = status, admin_id, now()
            s.flush()
            if decision == "allow" and review.user_id:
                user = s.get(User, review.user_id, with_for_update=True)
                root = s.get(SafetyReview, user.guardrail_block_id) if user.guardrail_block_id else None
                remaining = s.scalar(
                    select(SafetyReview.id)
                    .where(
                        SafetyReview.user_id == user.id,
                        SafetyReview.origin == "human",
                        SafetyReview.allowed.is_(False),
                        SafetyReview.review_status != "allowed",
                    )
                    .limit(1)
                )
                if root and allowed(root) and not remaining:
                    set_block(
                        s,
                        user,
                        False,
                        admin_id=admin_id,
                        reason="Guardrail decision reversed after review",
                        source="guardrail_review",
                    )
            if review.chain_id and decision == "allow":
                chain = s.get(Chain, review.chain_id, with_for_update=True)
                if chain.safety_status == "flagged":
                    chain.safety_status = "pending"
        return {"ok": True}
