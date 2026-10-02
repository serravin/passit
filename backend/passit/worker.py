import argparse
import logging
import time
from datetime import timedelta

from sqlalchemy import and_, or_, select

from .ai import CreativeAI
from .config import Settings
from .db import Database
from .domain import assign, lock_chain, queue, story_context, timeout
from .guardrail import Guardrail, content_hash
from .models import (
    AIAssignment,
    AIProfile,
    Chain,
    GeneratedTextProof,
    PlatformSettings,
    Turn,
    WorkItem,
    now,
    uid,
)
from .telemetry import measured_generate

log = logging.getLogger("passit.worker")


class Worker:
    def __init__(self, db, settings, ai=None):
        self.db = db
        self.ai = ai or CreativeAI(settings)
        self.guardrail = Guardrail(db, settings)

    def reconcile(self):
        # Hold at most one aggregate lock per transaction. Multiple reconcilers and
        # submission workers can then operate without reversing chain lock order.
        with self.db.sessions() as s:
            overdue = list(
                s.scalars(
                    select(Turn.id).where(Turn.status != "submitted", Turn.deadline_at <= now()).limit(100)
                )
            )
            chains = list(s.scalars(select(Chain.id).where(Chain.status == "active").limit(100)))
            unchecked = list(s.scalars(select(Chain.id).where(Chain.safety_status == "pending").limit(100)))
            guardrail_profile = s.get(AIAssignment, "guardrail")
            guardrail_id = guardrail_profile.profile_id if guardrail_profile else None
        if guardrail_id:
            for chain_id in unchecked:
                with self.db.transaction() as s:
                    key = f"guard_scan:{chain_id}:{guardrail_id}"
                    item = s.scalar(select(WorkItem).where(WorkItem.key == key).with_for_update())
                    if item and item.status == "done":
                        item.status, item.attempts, item.available_at = "pending", 0, now()
                    elif not item:
                        queue(s, "guard_scan", chain_id, key)
        for turn_id in overdue:
            with self.db.transaction() as s:
                timeout(s, turn_id)
        with self.db.transaction() as s:
            for item in s.scalars(
                select(WorkItem)
                .where(WorkItem.status == "processing", WorkItem.lease_until < now())
                .with_for_update(skip_locked=True)
                .limit(100)
            ):
                item.status = "pending"
                item.lease_token = None
        for chain_id in chains:
            with self.db.transaction() as s:
                chain = lock_chain(s, chain_id)
                if chain.status != "active":
                    continue
                active = s.scalar(select(Turn).where(Turn.chain_id == chain.id, Turn.status != "submitted"))
                if not active:
                    previous = list(
                        s.scalars(select(Turn).where(Turn.chain_id == chain.id).order_by(Turn.position))
                    )
                    queue(s, "handoff", chain.id, f"handoff:{chain.id}:{len(previous)}")

    def claim(self):
        with self.db.transaction() as s:
            item = s.scalar(
                select(WorkItem)
                .where(
                    or_(
                        and_(WorkItem.status == "pending", WorkItem.available_at <= now()),
                        and_(WorkItem.status == "processing", WorkItem.lease_until < now()),
                    )
                )
                .order_by(WorkItem.available_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if not item:
                return None
            item.status = "processing"
            item.lease_token = uid()
            item.lease_until = now() + timedelta(seconds=120)
            item.attempts += 1
            return item.id, item.lease_token

    def process(self, item_id, token):
        # Read immutable task/profile snapshot, then run inference outside the transaction.
        with self.db.sessions() as s:
            item = s.get(WorkItem, item_id)
            task, aggregate = item.task, item.aggregate_id
            profile = s.get(AIProfile, item.profile_id) if item.profile_id else None
            assignment = s.get(AIAssignment, "guardrail")
            guardrail_id = assignment.profile_id if assignment else None
            if task in {"handoff", "title"}:
                chain = s.get(Chain, aggregate)
                # The first handoff contains only the creator's setup. Later turns
                # must not change a delayed title's context or enter queue payloads.
                context = (
                    {"setup": chain.setup, "story": [chain.setup], "rules": chain.rules}
                    if task == "title"
                    else story_context(s, chain)
                )
                active = s.scalar(select(Turn).where(Turn.chain_id == aggregate, Turn.status != "submitted"))
                skip = chain.status != "active" or bool(active) if task == "handoff" else bool(chain.title)
            elif task == "suggestions":
                turn = s.get(Turn, aggregate)
                context = {**story_context(s, s.get(Chain, turn.chain_id)), "motive_id": turn.motive_id}
                skip = turn.status == "submitted" or turn.suggestions is not None
            else:
                context, skip = {}, True
            chain_id = turn.chain_id if task == "suggestions" else aggregate
            output = (
                measured_generate(
                    self.db, self.ai, profile, task, context, chain_id=chain_id, work_item_id=item_id
                )
                if not skip
                else None
            )
        if task == "guard_scan":
            self.guardrail.scan_chain(aggregate, profile_id=profile.id, work_item_id=item_id)
        elif output and task == "suggestions":
            safety_context = {
                "setup": context["setup"],
                "rules": context["rules"],
                "previous_contributions": context["story"][-3:],
            }
            for candidate in output["suggestions"]:
                self.guardrail.check_generated(
                    candidate,
                    context=safety_context,
                    kind="suggestion",
                    chain_id=chain_id,
                    profile_id=guardrail_id,
                    work_item_id=item_id,
                )
        elif output and task == "title":
            self.guardrail.check_generated(
                output["title"],
                context={"setup": context["setup"]},
                kind="title",
                chain_id=chain_id,
                profile_id=guardrail_id,
                work_item_id=item_id,
            )
        with self.db.transaction() as s:
            s.get(PlatformSettings, 1, with_for_update=True)
            item = s.scalar(select(WorkItem).where(WorkItem.id == item_id).with_for_update())
            if item.status != "processing" or item.lease_token != token:
                return
            if output and task in {"suggestions", "title"}:
                current = s.get(AIAssignment, "guardrail")
                if not current or current.profile_id != guardrail_id:
                    raise ValueError("Guardrail configuration changed; retry generation")
            if task == "handoff" and output:
                chain = lock_chain(s, aggregate)
                # Assignment and recipient are persisted atomically; duplicate deliveries are harmless.
                assign(s, chain, output["motive_id"])
            elif task == "suggestions" and output:
                turn = s.get(Turn, aggregate)
                lock_chain(s, turn.chain_id)
                s.refresh(turn, with_for_update=True)
                if turn.status != "submitted" and turn.suggestions is None:
                    turn.suggestions = output["suggestions"]
                    turn.fallback_index = output["fallback_index"]
                    for candidate in output["suggestions"]:
                        s.add(
                            GeneratedTextProof(
                                user_id=turn.user_id,
                                turn_id=turn.id,
                                kind="suggestion",
                                content_hash=content_hash(candidate),
                            )
                        )
                    s.flush()
                    timeout(s, turn.id)
            elif task == "title" and output:
                chain = lock_chain(s, aggregate)
                if not chain.title:
                    chain.title = output["title"]
            elif task == "timeout":
                timeout(s, aggregate)
            item.status = "done"
            item.payload = {}
            item.lease_token = None
            item.error_code = None

    def run_once(self):
        claim = self.claim()
        if not claim:
            return False
        item_id, token = claim
        try:
            self.process(item_id, token)
        except Exception as exc:
            # No private stories, model output, response body or credentials in logs.
            code = type(exc).__name__
            log.warning("Work item %s failed (%s)", item_id, code)
            with self.db.transaction() as s:
                item = s.scalar(select(WorkItem).where(WorkItem.id == item_id).with_for_update())
                if item.status == "processing" and item.lease_token == token:
                    profile = s.get(AIProfile, item.profile_id) if item.profile_id else None
                    limit = profile.max_retries + 1 if profile else 4
                    item.status = "failed" if item.attempts >= limit else "pending"
                    item.available_at = now() + timedelta(seconds=min(60, 2**item.attempts))
                    item.error_code = code
                    item.lease_token = None
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Reconcile and drain currently available work")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    settings.validate()
    worker = Worker(Database(settings.database_url), settings)
    last_scan = 0
    while True:
        if time.monotonic() - last_scan >= 10:
            worker.reconcile()
            last_scan = time.monotonic()
        worked = worker.run_once()
        if args.once and not worked:
            break
        if not worked:
            time.sleep(1)


if __name__ == "__main__":
    main()
