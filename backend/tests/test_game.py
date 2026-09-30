from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi import HTTPException
from passit.domain import submit, timeout
from passit.models import (
    AIAssignment,
    Chain,
    Participant,
    Turn,
    UserSettings,
    WorkItem,
    now,
)
from sqlalchemy import func, select

from .conftest import drain, finish, launch, login


def test_complete_game_private_until_unanimous_publication(game):
    client, db, worker, users = game
    chain = launch(client, users)
    cid = chain["id"]
    assert chain["completed_contributions"] == 1  # setup consumes the creator's turn
    drain(worker)
    chain = client.get(f"/api/chains/{cid}").json()
    assert chain["title"] != "Untitled Chain"
    assert chain["turns"][0]["motive"]["id"] != "end"
    assert "suggestions" not in chain["turns"][0]  # creator cannot see another player's suggestions
    login(client, users[-1])
    assert client.get(f"/api/chains/{cid}").status_code == 404
    assert client.put(f"/api/likes/turns/{chain['turns'][0]['id']}").status_code == 404
    login(client, users[0])
    chain = finish(client, worker, users, cid)
    assert chain["participant_count"] == 3
    assert len(chain["turns"]) == 2
    assert chain["turns"][-1]["motive"]["id"] == "end"
    assert len({t["user"]["id"] for t in chain["turns"]}) == 2
    assert client.get("/api/discover").json() == []
    login(client, users[0])
    assert client.post(f"/api/chains/{cid}/publication", json={"decision": "request"}).status_code == 200
    login(client, users[1])
    chain = client.post(f"/api/chains/{cid}/publication", json={"decision": "approved"}).json()
    assert chain["visibility"] == "participants_only"
    login(client, users[2])
    chain = client.post(f"/api/chains/{cid}/publication", json={"decision": "approved"}).json()
    assert chain["visibility"] == "published"
    client.post("/api/logout")
    assert client.get(f"/api/chains/{cid}").status_code == 200
    assert len(client.get("/api/discover").json()) == 1
    login(client, users[-1])
    assert client.put(f"/api/likes/chains/{cid}").status_code == 200
    client.put(f"/api/likes/chains/{cid}")
    tid = chain["turns"][0]["id"]
    client.put(f"/api/likes/turns/{tid}")
    viewed = client.get(f"/api/chains/{cid}").json()
    assert viewed["likes"] == 1 and viewed["turns"][0]["likes"] == 1
    client.delete(f"/api/likes/chains/{cid}")
    assert client.get(f"/api/chains/{cid}").json()["likes"] == 0
    with db.sessions() as s:
        assert all(t.suggestions is None and t.fallback_index is None for t in s.scalars(select(Turn)))


def test_rejection_and_nonmember_publication(game):
    client, _, worker, users = game
    chain = launch(client, users, member_ids=[users[1].id])
    cid = chain["id"]
    assert client.post(f"/api/chains/{cid}/publication", json={"decision": "request"}).status_code == 409
    finish(client, worker, users, cid)
    login(client, users[-1])
    assert client.post(f"/api/chains/{cid}/publication", json={"decision": "request"}).status_code == 404
    login(client, users[0])
    client.post(f"/api/chains/{cid}/publication", json={"decision": "request"})
    login(client, users[1])
    response = client.post(f"/api/chains/{cid}/publication", json={"decision": "rejected"})
    assert response.json()["publication_status"] == "rejected"
    assert client.post(f"/api/chains/{cid}/publication", json={"decision": "approved"}).status_code == 409
    assert client.get("/api/discover").json() == []


def test_delayed_preparation_uses_exact_fallback_and_rejects_late_human(game):
    client, db, worker, users = game
    cid = launch(client, users, member_ids=[users[1].id])["id"]
    assert worker.run_once()  # handoff only
    with db.transaction() as s:
        turn = s.scalar(select(Turn).where(Turn.chain_id == cid))
        tid = turn.id
        turn.deadline_at = now() - timedelta(seconds=1)
        deadline = turn.deadline_at
    login(client, users[1])
    assert client.post(f"/api/chains/{cid}/turns/{tid}/submit", json={"text": "Late"}).status_code == 409
    worker.reconcile()
    with db.sessions() as s:
        assert s.get(Turn, tid).status == "generating"
        assert s.get(Turn, tid).suggestions is None
    expected = worker.ai.demo("suggestions", {"motive_id": "end"})["suggestions"][0]
    drain(worker)
    with db.transaction() as s:
        turn = s.get(Turn, tid)
        assert turn.text == expected and turn.ai_generated and not turn.ai_assisted
        assert turn.suggestions is None
        assert turn.deadline_at.replace(tzinfo=deadline.tzinfo) == deadline
        assert s.get(Chain, cid).status == "completed"
        timeout(s, tid)  # duplicate deadline delivery
    assert client.post(f"/api/chains/{cid}/turns/{tid}/submit", json={"text": "Replacement"}).status_code == 409
    login(client, users[0])
    client.post(f"/api/chains/{cid}/publication", json={"decision": "request"})
    assert client.get(f"/api/chains/{cid}").json()["visibility"] == "participants_only"
    login(client, users[1])  # timed-out participant's explicit approval is still necessary
    assert client.post(f"/api/chains/{cid}/publication", json={"decision": "approved"}).json()["visibility"] == "published"


def test_double_submission_and_duplicate_handoff(game):
    client, db, worker, users = game
    cid = launch(client, users)["id"]
    drain(worker)
    with db.sessions() as s:
        turn = s.scalar(select(Turn).where(Turn.chain_id == cid))
        tid, user_id = turn.id, turn.user_id
    def send(text):
        try:
            with db.transaction() as s:
                submit(s, cid, tid, user_id, text, False)
            return "saved"
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(send, ["First", "Second"]))
    assert sorted(str(x) for x in results) == ["409", "saved"]
    drain(worker)
    with db.transaction() as s:
        item = s.scalar(select(WorkItem).where(WorkItem.key == f"handoff:{cid}:1"))
        item.status = "pending"
    drain(worker)
    with db.sessions() as s:
        assert s.scalar(select(func.count()).select_from(Turn).where(Turn.chain_id == cid)) == 2
        assert s.scalar(select(func.count()).select_from(Participant).where(Participant.chain_id == cid, Participant.contributed.is_(True))) == 2


def test_human_submission_timeout_race_and_exact_deadline(game):
    client, db, worker, users = game
    cid = launch(client, users, member_ids=[users[1].id])["id"]
    drain(worker)
    with db.sessions() as s:
        turn = s.scalar(select(Turn).where(Turn.chain_id == cid))
        tid, user_id, deadline = turn.id, turn.user_id, turn.deadline_at
    from passit.domain import utc
    deadline = utc(deadline)
    def human():
        try:
            with db.transaction() as s:
                submit(s, cid, tid, user_id, "I made it.", False, timestamp=deadline - timedelta(microseconds=1))
            return True
        except HTTPException:
            return False
    def ai_timeout():
        with db.transaction() as s:
            timeout(s, tid, timestamp=deadline)
    with ThreadPoolExecutor(max_workers=2) as pool:
        human_future = pool.submit(human)
        timeout_future = pool.submit(ai_timeout)
        human_future.result()
        timeout_future.result()
    with db.sessions() as s:
        turn = s.get(Turn, tid)
        assert turn.status == "submitted" and turn.text
        assert s.get(Chain, cid).status == "completed"
        assert s.scalar(select(func.count()).select_from(Turn)) == 1


@pytest.mark.parametrize("changes", [
    {"member_ids": []}, {"min_participants": 6, "max_participants": 5},
    {"max_participants": 21}, {"turn_timeout_seconds": 0}, {"title": "Not allowed"},
    {"motive_id": "worse"}, {"visibility": "published"},
])
def test_launch_validation(game, changes):
    client, _, _, users = game
    login(client, users[0])
    response = client.post("/api/chains", json={"setup": "A premise", "member_ids": [users[1].id], **changes})
    assert response.status_code == 422


def test_random_optin_and_admin_default_cap(game):
    client, db, _, users = game
    login(client, users[0])
    with db.transaction() as s:
        for pref in s.scalars(select(UserSettings)):
            pref.allow_random_participation = False
    response = client.post("/api/chains", json={"setup": "A premise", "group_mode": "random"})
    assert response.status_code == 422
    login(client, users[1])
    client.put("/api/me/settings", json={"allow_random_participation": True, "notifications_enabled": False})
    assert client.put("/api/admin/platform", json={"max_participants_per_chain": 2}).status_code == 403
    login(client, users[0])
    assert client.put("/api/admin/platform", json={"max_participants_per_chain": 2}).status_code == 200
    response = client.post("/api/chains", json={"setup": "A premise", "group_mode": "random"})
    assert response.status_code == 201
    assert response.json()["max_participants"] == 2
    assert {p["id"] for p in response.json()["participants"]} == {users[0].id, users[1].id}


def test_group_snapshot_and_oversize_not_truncated(game):
    client, _, _, users = game
    login(client, users[0])
    group = client.post("/api/groups", json={"name": "Friends", "member_ids": [u.id for u in users[1:4]]}).json()
    payload = {"setup": "A premise", "group_mode": "saved_group", "source_group_id": group["id"], "max_participants": 3}
    assert client.post("/api/chains", json=payload).status_code == 422
    response = client.post("/api/chains", json={**payload, "member_ids": [users[1].id]})
    assert response.status_code == 201
    cid = response.json()["id"]
    client.put(f"/api/groups/{group['id']}", json={"name": "New name", "member_ids": [users[2].id]})
    chain = client.get(f"/api/chains/{cid}").json()
    assert {p["id"] for p in chain["participants"]} == {users[0].id, users[1].id}


def test_suggestions_edit_flag_and_unauthorized_submission(game):
    client, db, worker, users = game
    cid = launch(client, users, member_ids=[users[1].id])["id"]
    drain(worker)
    chain = client.get(f"/api/chains/{cid}").json()
    tid = chain["turns"][0]["id"]
    assert client.post(f"/api/chains/{cid}/turns/{tid}/submit", json={"text": "Impostor"}).status_code == 403
    login(client, users[1])
    turn = client.get(f"/api/chains/{cid}").json()["turns"][0]
    assert len(turn["suggestions"]) == 3
    response = client.post(f"/api/chains/{cid}/turns/{tid}/submit", json={"text": turn["suggestions"][0] + " Edited.", "ai_assisted": True})
    assert response.status_code == 200
    assert response.json()["turns"][0]["ai_assisted"]
    with db.sessions() as s:
        assert s.get(Turn, tid).suggestions is None


def test_profile_validation_revision_pinning_and_dead_letter(game):
    client, db, worker, users = game
    cid = launch(client, users)["id"]
    login(client, users[0])
    created = client.post("/api/admin/profiles", json={"provider": "demo", "model_reference": "demo-v2"}).json()
    profile_id = created["id"]
    assert client.post(f"/api/admin/profiles/{profile_id}/activate", json={}).status_code == 422
    assert client.post(f"/api/admin/profiles/{profile_id}/validate").status_code == 200
    assert client.post(f"/api/admin/profiles/{profile_id}/activate", json={}).status_code == 200
    with db.sessions() as s:
        item = s.scalar(select(WorkItem).where(WorkItem.aggregate_id == cid))
        assert item.profile_id != profile_id
        assert s.get(AIAssignment, "default").profile_id == profile_id
    class BrokenAI:
        def generate(self, *args):
            raise ValueError("private story must not leak")
    worker.ai = BrokenAI()
    for _ in range(4):
        worker.run_once()
        with db.transaction() as s:
            for item in s.scalars(select(WorkItem).where(WorkItem.status == "pending")):
                item.available_at = now()
    state = client.get("/api/admin").json()
    assert state["failed_work"][0]["error_code"] == "ValueError"
    assert "private story" not in str(state)
    assert client.post(f"/api/admin/work/{state['failed_work'][0]['id']}/retry").status_code == 200
    from passit.ai import CreativeAI
    worker.ai = CreativeAI(client.app.state.settings)
    drain(worker)
    assert client.get(f"/api/chains/{cid}").json()["turns"]


def test_stale_worker_lease_is_recovered(game):
    client, db, worker, users = game
    cid = launch(client, users)["id"]
    claim = worker.claim()
    with db.transaction() as s:
        item = s.get(WorkItem, claim[0])
        item.lease_until = now() - timedelta(seconds=1)
    worker.reconcile()
    drain(worker)
    assert len(client.get(f"/api/chains/{cid}").json()["turns"]) == 1
    worker.process(*claim)  # stale worker cannot commit after lease replacement
    assert len(client.get(f"/api/chains/{cid}").json()["turns"]) == 1


def test_cookie_csrf_and_auth_requirements(game):
    client, _, _, users = game
    assert client.get("/api/me").status_code == 401
    login(client, users[0])
    assert client.post("/api/chains", json={"setup": "Bad origin"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/chains", json={"setup": "No origin"}, headers={"Origin": ""}).status_code == 403
