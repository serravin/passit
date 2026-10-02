import time
from types import SimpleNamespace

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from passit.api import create_app
from passit.config import Settings
from passit.db import Database
from passit.models import User, UserSettings
from passit.seed import initialize
from sqlalchemy import select


def test_production_oidc_validates_issuer_audience_signature_expiry_and_subject(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/oidc.db")
    db.create_schema()
    initialize(db)
    settings = Settings(
        mode="production",
        database_url="postgresql+psycopg://unused",
        issuer="https://identity.example/",
        audience="passit-api",
        jwks_url="https://identity.example/keys",
        admin_subjects={"admin-subject"},
    )
    app = create_app(settings, db)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app.state.jwks = SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key())
    )
    claims = {
        "iss": settings.issuer,
        "aud": settings.audience,
        "sub": "admin-subject",
        "exp": int(time.time()) + 300,
        "name": "An admin",
    }

    def header(data, signing_key=key):
        return {"Authorization": "Bearer " + jwt.encode(data, signing_key, algorithm="RS256")}

    with TestClient(app) as client:
        assert client.get("/api/me").status_code == 401
        valid = client.get("/api/me", headers=header(claims))
        assert valid.status_code == 200 and valid.json()["admin"]
        user_id = valid.json()["id"]
        for invalid in (
            {**claims, "iss": "https://evil.example/"},
            {**claims, "aud": "other-api"},
            {**claims, "exp": int(time.time()) - 60},
        ):
            assert client.get("/api/me", headers=header(invalid)).status_code == 401
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        assert client.get("/api/me", headers=header(claims, other_key)).status_code == 401
        # Email/name changes never create a new local identity.
        again = client.get("/api/me", headers=header({**claims, "name": "A renamed person"}))
        assert again.json()["id"] == user_id
        ordinary = client.get("/api/me", headers=header({**claims, "sub": "ordinary"})).json()
        assert not ordinary["admin"]
        assert not ordinary["settings"]["allow_random_participation"]
        ordinary_headers = header({**claims, "sub": "ordinary"})
        assert client.get("/api/admin/users", headers=ordinary_headers).status_code == 403
        assert (
            client.put(
                f"/api/admin/users/{ordinary['id']}/block", json={"blocked": True}, headers=header(claims)
            ).status_code
            == 200
        )
        # A valid JWT cannot bypass a local block; neither can a changed name.
        assert client.get("/api/me", headers=ordinary_headers).status_code == 403
        assert (
            client.get(
                "/api/discover", headers=header({**claims, "sub": "ordinary", "name": "Renamed"})
            ).status_code
            == 403
        )
        assert (
            client.put(
                f"/api/admin/users/{ordinary['id']}/block", json={"blocked": False}, headers=header(claims)
            ).status_code
            == 200
        )
        assert client.get("/api/me", headers=ordinary_headers).json()["id"] == ordinary["id"]
        # The current allowlist protects admins even before their next sign-in updates the cached flag.
        settings.admin_subjects.add("ordinary")
        assert (
            client.put(
                f"/api/admin/users/{ordinary['id']}/block", json={"blocked": True}, headers=header(claims)
            ).status_code
            == 422
        )
        assert client.post("/api/demo/login", json={"user_id": user_id}).status_code == 404
        assert client.get("/api/demo/accounts").status_code == 404
    with db.sessions() as s:
        assert len(list(s.scalars(select(User)))) == 2
        assert not s.get(UserSettings, user_id).allow_random_participation


def test_production_configuration_requires_postgres_and_oidc():
    import pytest

    with pytest.raises(ValueError):
        Settings(mode="production", database_url="sqlite:///bad.db").validate()
    with pytest.raises(ValueError):
        Settings(mode="production", database_url="postgresql+psycopg://unused").validate()
