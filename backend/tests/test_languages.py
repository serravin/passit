import json
import re
from pathlib import Path

import pytest

from .conftest import login


@pytest.mark.parametrize("language", ["en", "de", "fr", "it"])
def test_language_preference_survives_sign_in(game, language):
    client, _, _, users = game
    login(client, users[0])
    original = client.get("/api/me").json()["settings"]
    settings = {**original, "language": language}
    assert client.put("/api/me/settings", json=settings).status_code == 200
    client.post("/api/logout")
    login(client, users[0])
    assert client.get("/api/me").json()["settings"] == settings
    assert client.put("/api/me/settings", json={**settings, "language": "es"}).status_code == 422
    assert client.get("/api/me").json()["settings"] == settings


def test_translation_catalogs_cover_interface_and_preserve_placeholders():
    source = Path(__file__).resolve().parents[2] / "frontend" / "src"
    catalogs = [json.loads((source / "locales" / f"{lang}.json").read_text()) for lang in ("de", "fr", "it")]
    keys = set(catalogs[0])
    for catalog in catalogs:
        assert set(catalog) == keys
        for key, translation in catalog.items():
            assert translation.strip(), key
            assert set(re.findall(r"\{\w+\}", key)) == set(re.findall(r"\{\w+\}", translation)), key
    # Static calls use English as their fallback; every one must be translated.
    for file in (
        "App.tsx",
        "Admin.tsx",
        "Dashboard.tsx",
        "UserManagement.tsx",
        "SafetyReviews.tsx",
        "AccountNotices.tsx",
        "i18n.ts",
    ):
        for literal in re.findall(r'\bt\(\s*("(?:[^"\\]|\\.)*")', (source / file).read_text()):
            assert json.loads(literal) in keys, (file, literal)
    from passit.seed import MOTIVES

    for _, label, _ in MOTIVES:
        assert label in keys
