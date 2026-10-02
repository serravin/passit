from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Launch(Input):
    setup: str = Field(min_length=1, max_length=1500)
    setup_ai_assisted: bool = False
    rules: str = Field(default="", max_length=500)
    group_mode: Literal["friends", "saved_group", "random"] = "friends"
    source_group_id: str | None = None
    member_ids: list[str] = Field(default_factory=list, max_length=99)
    turn_timeout_seconds: int = Field(default=900, gt=0, le=604800)
    min_participants: int = Field(default=2, ge=2)
    max_participants: int | None = Field(default=None, ge=2)


class Submission(Input):
    text: str = Field(min_length=1, max_length=1500)
    ai_assisted: bool = False


class Decision(Input):
    decision: Literal["request", "approved", "rejected"]


class Preferences(Input):
    allow_random_participation: bool
    notifications_enabled: bool
    language: Literal["en", "de", "fr", "it"] = "en"


class GroupInput(Input):
    name: str = Field(min_length=1, max_length=80)
    member_ids: list[str] = Field(default_factory=list, max_length=100)


class FriendInput(Input):
    user_id: str


class FriendResponse(Input):
    accept: bool


class PlatformInput(Input):
    max_participants_per_chain: int = Field(ge=2, le=100)


class UserBlockInput(Input):
    blocked: bool
    reason: str | None = Field(default=None, max_length=500)


class ProfileInput(Input):
    provider: Literal["demo", "azure_openai"] = "azure_openai"
    endpoint: str = Field(default="", max_length=500)
    deployment_name: str = Field(default="", max_length=100, pattern=r"^[a-zA-Z0-9_.-]*$")
    model_reference: str = Field(default="", max_length=100)
    api_version: str = Field(default="2024-10-21", max_length=40)
    auth_mode: Literal["managed_identity", "environment_reference"] = "managed_identity"
    credential_reference: Literal["PASSIT_AI_API_KEY"] = "PASSIT_AI_API_KEY"
    generation_parameters: dict = Field(default_factory=lambda: {"max_completion_tokens": 500})
    request_timeout_seconds: int = Field(default=30, ge=1, le=60)
    max_retries: int = Field(default=3, ge=0, le=8)
    prompt_version: Literal["v1"] = "v1"
    input_price_per_million: float | None = Field(default=None, ge=0, le=100000, allow_inf_nan=False)
    output_price_per_million: float | None = Field(default=None, ge=0, le=100000, allow_inf_nan=False)

    @field_validator("generation_parameters")
    @classmethod
    def parameters(cls, value):
        if set(value) - {"temperature", "max_tokens", "max_completion_tokens"}:
            raise ValueError("Unsupported generation parameter")
        if "max_tokens" in value and "max_completion_tokens" in value:
            raise ValueError("Choose one token limit")
        for key, number in value.items():
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                raise ValueError("Generation parameters must be numeric")
            if key == "temperature":
                if not 0 <= number <= 2:
                    raise ValueError("Temperature must be between 0 and 2")
            elif not isinstance(number, int) or not 64 <= number <= 4000:
                raise ValueError("Token limits must be integers between 64 and 4000")
        return value


class ActivateProfile(Input):
    task: Literal["default", "handoff", "suggestions", "title", "setup"] = "default"


class SetupRequest(Input):
    theme: str = Field(default="", max_length=200)
