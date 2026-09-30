import os

import pytest
from fastapi.testclient import TestClient
from passit.api import create_app
from passit.config import Settings
from passit.db import Database
from passit.models import User
from passit.worker import Worker
from sqlalchemy import select


@pytest.fixture
def game(tmp_path):
    url = os.getenv("PASSIT_TEST_DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    db = Database(url)
    if os.getenv("PASSIT_TEST_DATABASE_URL"):
        from passit.models import Base

        Base.metadata.drop_all(db.engine)
    settings = Settings(database_url=url)
    app = create_app(settings, db)
    with TestClient(app, headers={"Origin": settings.origin}) as client:
        with db.sessions() as s:
            users = list(s.scalars(select(User).order_by(User.name)))
        worker = Worker(db, settings)
        yield client, db, worker, users
    db.engine.dispose()


def login(client, user):
    response = client.post("/api/demo/login", json={"user_id": user.id})
    assert response.status_code == 200, response.text


def launch(client, users, **options):
    login(client, users[0])
    payload = {
        "setup": "The hotel gave me a crown instead of a room key.",
        "member_ids": [u.id for u in users[1:3]],
        **options,
    }
    response = client.post("/api/chains", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def drain(worker):
    for _ in range(50):
        if not worker.run_once():
            return
    raise AssertionError("Worker did not settle")


def finish(client, worker, users, chain_id):
    for _ in range(len(users)):
        drain(worker)
        chain = client.get(f"/api/chains/{chain_id}").json()
        active = next((t for t in chain["turns"] if t["status"] != "submitted"), None)
        if not active:
            assert chain["status"] == "completed"
            return chain
        login(client, next(u for u in users if u.id == active["user"]["id"]))
        response = client.post(
            f"/api/chains/{chain_id}/turns/{active['id']}/submit",
            json={"text": "The crown requested a performance review."},
        )
        assert response.status_code == 200, response.text
    raise AssertionError("Chain did not finish")
