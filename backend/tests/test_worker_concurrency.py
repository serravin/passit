from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from passit.models import Chain, Turn, WorkItem, now
from sqlalchemy import select

from .conftest import launch


def test_multiple_workers_and_reconcilers_advance_once_without_deadlock(game):
    client, db, worker, users = game
    ids = [launch(client, users, member_ids=[users[1].id])["id"] for _ in range(6)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: worker.run_once(), range(40)))
    with db.transaction() as s:
        turns = list(s.scalars(select(Turn)))
        assert len(turns) == len(ids)
        for turn in turns:
            assert turn.suggestions and turn.fallback_index == 0
            turn.deadline_at = now() - timedelta(seconds=1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: worker.reconcile(), range(4)))
    with db.sessions() as s:
        assert all(s.get(Chain, cid).status == "completed" for cid in ids)
        assert all(t.ai_generated and t.suggestions is None for t in s.scalars(select(Turn)))
        assert not list(s.scalars(select(WorkItem).where(WorkItem.status == "failed")))
        assert all("story" not in w.payload for w in s.scalars(select(WorkItem)))
