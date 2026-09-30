import pytest
from passit.ai import CreativeAI, validate_output
from passit.config import Settings
from passit.models import AIProfile


def test_motive_and_suggestion_schema_validation():
    with pytest.raises(ValueError):
        validate_output("handoff", {"motive_id": "end"}, {"eligible_motives": ["worse"]})
    with pytest.raises(ValueError):
        validate_output("suggestions", {"suggestions": ["Same", "Same", "Same"], "fallback_index": 0}, {})
    with pytest.raises(ValueError):
        validate_output("suggestions", {"suggestions": ["a", "b", "c"], "fallback_index": 3}, {})


def test_azure_endpoint_is_approved_before_any_credential_access():
    adapter = CreativeAI(Settings(ai_allowed_hosts={"example.openai.azure.com"}))
    for endpoint in ("http://example.openai.azure.com", "https://evil.example", "https://user:password@example.openai.azure.com"):
        profile = AIProfile(provider="azure_openai", endpoint=endpoint)
        with pytest.raises(ValueError):
            adapter.azure(profile, "title", {})


def test_demo_ai_refused_in_production():
    with pytest.raises(ValueError):
        CreativeAI(Settings(mode="production")).generate(AIProfile(provider="demo"), "title", {})
