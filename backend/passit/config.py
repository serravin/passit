import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass
class Settings:
    mode: str = field(default_factory=lambda: os.getenv("PASSIT_MODE", "demo"))
    database_url: str = field(
        default_factory=lambda: os.getenv("PASSIT_DATABASE_URL", "sqlite:///./passit.db")
    )
    origin: str = field(default_factory=lambda: os.getenv("PASSIT_ORIGIN", "http://localhost:5173"))
    issuer: str = field(default_factory=lambda: os.getenv("PASSIT_OIDC_ISSUER", ""))
    audience: str = field(default_factory=lambda: os.getenv("PASSIT_OIDC_AUDIENCE", ""))
    jwks_url: str = field(default_factory=lambda: os.getenv("PASSIT_OIDC_JWKS_URL", ""))
    admin_subjects: set[str] = field(
        default_factory=lambda: set(filter(None, os.getenv("PASSIT_ADMIN_SUBJECTS", "").split(",")))
    )
    ai_allowed_hosts: set[str] = field(
        default_factory=lambda: set(filter(None, os.getenv("PASSIT_AI_ALLOWED_HOSTS", "").split(",")))
    )

    @property
    def allowed_origins(self) -> set[str]:
        origins = {self.origin}
        parsed = urlsplit(self.origin)
        if self.mode == "demo" and parsed.hostname in {"localhost", "127.0.0.1"}:
            alias = "127.0.0.1" if parsed.hostname == "localhost" else "localhost"
            port = f":{parsed.port}" if parsed.port is not None else ""
            origins.add(f"{parsed.scheme}://{alias}{port}")
        return origins

    def validate(self):
        if self.mode not in {"demo", "production"}:
            raise ValueError("PASSIT_MODE must be demo or production")
        if self.mode == "production":
            if not self.database_url.startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL")
            if not all((self.issuer, self.audience, self.jwks_url)):
                raise ValueError("Production requires OIDC issuer, audience and JWKS URL")
            if not self.jwks_url.startswith("https://"):
                raise ValueError("JWKS URL must use HTTPS")
