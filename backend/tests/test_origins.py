import pytest
from fastapi.testclient import TestClient
from passit.api import create_app
from passit.config import Settings


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_demo_accepts_loopback_alias_on_same_port(tmp_path, host):
    settings = Settings(origin=f"http://{host}:8080", database_url=f"sqlite:///{tmp_path}/origins.db")
    with TestClient(create_app(settings)) as client:
        user = client.get("/api/demo/accounts").json()[0]
        for origin in ("http://localhost:8080", "http://127.0.0.1:8080"):
            response = client.options(
                "/api/demo/login",
                headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
            )
            assert response.headers["access-control-allow-origin"] == origin
            assert (
                client.post(
                    "/api/demo/login", json={"user_id": user["id"]}, headers={"Origin": origin}
                ).status_code
                == 200
            )
        for origin in ("http://127.0.0.1:8081", "https://localhost:8080", "https://evil.example", ""):
            assert (
                client.post(
                    "/api/demo/login", json={"user_id": user["id"]}, headers={"Origin": origin}
                ).status_code
                == 403
            )


def test_production_does_not_add_loopback_alias():
    assert Settings(mode="production", origin="http://localhost:8080").allowed_origins == {
        "http://localhost:8080"
    }


def test_demo_remote_origin_does_not_add_loopback_alias():
    assert Settings(origin="https://passit.example").allowed_origins == {"https://passit.example"}
