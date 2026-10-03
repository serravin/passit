"""Exercise native dependencies, migrations and the game inside the built API image."""

import subprocess

import psycopg
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from passit.api import create_app
from passit.config import Settings
from passit.db import Database
from passit.worker import Worker

# Importing psycopg loads its native client library; RSA exercises cryptography.
assert psycopg.pq.version() > 0
rsa.generate_private_key(public_exponent=65537, key_size=2048)
subprocess.run(["alembic", "upgrade", "head"], check=True)
subprocess.run(["python", "-m", "passit.manage", "seed"], check=True)
settings = Settings()
db = Database(settings.database_url)
with TestClient(create_app(settings, db), headers={"Origin": settings.origin}) as client:
    health = client.get("/api/health")
    assert health.status_code == 200 and health.json()["status"] == "ok"
    accounts = client.get("/api/demo/accounts").json()
    assert len(accounts) >= 3
    response = client.post("/api/demo/login", json={"user_id": accounts[0]["id"]})
    assert response.status_code == 200
    response = client.post(
        "/api/chains",
        json={
            "setup": "The hotel handed me a crown instead of a room key.",
            "member_ids": [account["id"] for account in accounts[1:3]],
        },
    )
    assert response.status_code == 201, response.text
    chain_id = response.json()["id"]
    worker = Worker(db, settings)
    for _ in range(20):
        if not worker.run_once():
            break
    chain = client.get(f"/api/chains/{chain_id}")
    assert chain.status_code == 200
    assert any(turn["status"] != "submitted" for turn in chain.json()["turns"])
db.engine.dispose()
print("API container smoke passed: native libraries, migrations, authentication, story creation and worker")
