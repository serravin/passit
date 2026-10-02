from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from fastapi.testclient import TestClient
from passit.models import Chain, Turn, User, UserModerationEvent, UserSettings, now
from sqlalchemy import select

from .conftest import drain, launch, login


def block(client, user, blocked=True, reason=None):
    return client.put(f"/api/admin/users/{user.id}/block", json={"blocked": blocked, "reason": reason})


def test_admin_controls_authorization_search_audit_and_protected_accounts(game):
    client, db, _, users = game
    for path in ("/api/admin/users", "/api/admin/moderation"):
        assert client.get(path).status_code == 401
    assert block(client, users[1]).status_code == 401
    login(client, users[1])
    assert client.get("/api/admin/users").status_code == 403
    assert client.get("/api/admin/moderation").status_code == 403
    assert block(client, users[2]).status_code == 403
    login(client, users[0])
    assert block(client, users[0]).status_code == 422
    with db.transaction() as s:
        s.get(User, users[2].id).admin = True
    assert block(client, users[2]).status_code == 422
    assert client.put("/api/admin/users/missing/block", json={"blocked": True}).status_code == 404
    assert block(client, users[1], reason="x" * 501).status_code == 422
    assert (
        client.put(f"/api/admin/users/{users[1].id}/block", json={"blocked": True, "admin": True}).status_code
        == 422
    )
    assert client.get("/api/admin/users?status=unknown").status_code == 422
    assert client.get("/api/admin/users?limit=1000").status_code == 422
    assert client.get("/api/admin/users?offset=-1").status_code == 422
    page = client.get("/api/admin/users?limit=2").json()
    assert len(page["items"]) == 2 and page["total"] == len(users)
    second = client.get("/api/admin/users?limit=2&offset=2").json()
    assert not {u["id"] for u in page["items"]} & {u["id"] for u in second["items"]}
    assert client.get("/api/admin/users?q=jam").json()["items"][0]["id"] == users[1].id
    assert client.get("/api/admin/users?q=%25").json()["total"] == 0  # Search wildcards are literal.
    assert client.get("/api/admin/users", params={"q": users[1].id}).json()["total"] == 1
    response = block(client, users[1], reason="  Private abuse report  ")
    assert response.status_code == 200
    assert response.json()["blocked_at"] and response.json()["block_reason"] == "Private abuse report"
    assert client.get("/api/admin/users?status=blocked").json()["total"] == 1
    assert client.get("/api/admin/users?status=active").json()["total"] == len(users) - 1
    assert block(client, users[1], reason="A retried command").status_code == 200
    history = client.get("/api/admin/moderation").json()
    assert len(history) == 1 and history[0]["blocked"]
    assert history[0]["admin"]["id"] == users[0].id and history[0]["user"]["id"] == users[1].id
    assert history[0]["reason"] == "Private abuse report"
    assert block(client, users[1], False, "Appeal accepted").status_code == 200
    assert client.get("/api/admin/users?status=blocked").json()["total"] == 0
    with db.sessions() as s:
        assert s.get(User, users[1].id).block_reason is None
        assert len(list(s.scalars(select(UserModerationEvent)))) == 2


def test_existing_sessions_and_optional_auth_are_denied_and_unblocking_restores_access(game):
    client, _, worker, users = game
    story = launch(client, users, member_ids=[users[1].id])
    drain(worker)
    story = client.get(f"/api/chains/{story['id']}").json()
    turn = story["turns"][0]
    with TestClient(client.app, headers={"Origin": client.app.state.settings.origin}) as player:
        login(player, users[1])
        assert player.get("/api/me").status_code == 200
        assert block(client, users[1], reason="PRIVATE_REASON").status_code == 200
        for method, path, body in (
            ("GET", "/api/me", None),
            ("GET", "/api/chains", None),
            ("GET", "/api/notifications", None),
            ("GET", "/api/discover", None),
            ("GET", f"/api/chains/{story['id']}", None),
            ("POST", "/api/chains", {"setup": "Misuse", "member_ids": [users[0].id]}),
            ("POST", "/api/setup-assistance", {}),
            ("PUT", "/api/me/settings", {"allow_random_participation": True, "notifications_enabled": True}),
            ("POST", f"/api/chains/{story['id']}/turns/{turn['id']}/submit", {"text": "Blocked submission"}),
            ("POST", f"/api/chains/{story['id']}/publication", {"decision": "request"}),
            ("PUT", f"/api/likes/chains/{story['id']}", None),
        ):
            response = player.request(method, path, **({"json": body} if body is not None else {}))
            assert response.status_code == 403, (path, response.text)
            assert "PRIVATE_REASON" not in response.text
        assert player.post("/api/demo/login", json={"user_id": users[1].id}).status_code == 403
        assert block(client, users[1], False).status_code == 200
        assert player.get("/api/me").status_code == 200  # The original session is checked afresh.
        assert (
            player.post(
                f"/api/chains/{story['id']}/turns/{turn['id']}/submit",
                json={"text": "A restored contribution"},
            ).status_code
            == 200
        )
        assert block(client, users[1]).status_code == 200
        assert player.post("/api/logout").status_code == 200
        assert player.get("/api/me").status_code == 401
        assert player.get("/api/discover").status_code == 200  # Public browsing is available anonymously.


def test_blocked_players_are_excluded_from_friends_groups_and_random_casts(game):
    client, db, _, users = game
    login(client, users[0])
    group = client.get("/api/groups").json()[0]
    assert block(client, users[1]).status_code == 200
    assert users[1].id not in {u["id"] for u in client.get("/api/friends").json()["friends"]}
    assert client.get("/api/users?q=jam").json() == []
    assert client.post("/api/friends", json={"user_id": users[1].id}).status_code == 422
    assert (
        client.post("/api/groups", json={"name": "New cast", "member_ids": [users[1].id]}).status_code == 422
    )
    assert (
        client.post("/api/chains", json={"setup": "Blocked cast", "member_ids": [users[1].id]}).status_code
        == 422
    )
    saved = {"setup": "Saved cast", "group_mode": "saved_group", "source_group_id": group["id"]}
    assert client.post("/api/chains", json=saved).status_code == 422
    assert client.post("/api/chains", json={**saved, "member_ids": [users[2].id]}).status_code == 201
    with db.transaction() as s:
        for preference in s.scalars(select(UserSettings)):
            preference.allow_random_participation = preference.user_id in {users[1].id, users[2].id}
    random = client.post("/api/chains", json={"setup": "Random cast", "group_mode": "random"})
    assert random.status_code == 201
    assert {u["id"] for u in random.json()["participants"]} == {users[0].id, users[2].id}
    assert block(client, users[1], False).status_code == 200
    assert users[1].id in {u["id"] for u in client.get("/api/friends").json()["friends"]}
    assert client.post("/api/chains", json=saved).status_code == 201


def test_block_preserves_existing_story_and_requires_explicit_publication_consent(game):
    client, db, worker, users = game
    story = launch(client, users, member_ids=[users[1].id])
    drain(worker)
    with db.transaction() as s:
        turn = s.scalar(select(Turn).where(Turn.chain_id == story["id"]))
        tid = turn.id
        turn.deadline_at = now() - timedelta(seconds=1)
    assert block(client, users[1]).status_code == 200
    worker.reconcile()
    drain(worker)
    with db.sessions() as s:
        assert s.get(Turn, tid).ai_generated
        assert s.get(Chain, story["id"]).status == "completed"
        assert s.get(Chain, story["id"]).setup == story["setup"]
    response = client.post(f"/api/chains/{story['id']}/publication", json={"decision": "request"})
    assert response.json()["visibility"] == "participants_only"
    assert block(client, users[1], False).status_code == 200
    login(client, users[1])
    response = client.post(f"/api/chains/{story['id']}/publication", json={"decision": "approved"})
    assert response.json()["visibility"] == "published"


def test_concurrent_duplicate_blocks_create_one_action(game):
    client, db, _, users = game
    login(client, users[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: block(client, users[1]), range(2)))
    assert all(response.status_code == 200 for response in responses)
    with db.sessions() as s:
        assert len(list(s.scalars(select(UserModerationEvent)))) == 1
