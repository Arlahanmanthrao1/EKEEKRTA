from pydantic_settings import BaseSettings
from pydantic import Field, SecretStr, field_validator
import re
from typing import Literal


class Settings(BaseSettings):
    # SQLite by default so the project runs with zero setup.
    # Swap to a Postgres URL (postgresql://user:pass@host/db) when you're ready -
    # SQLAlchemy handles the switch, no code changes needed.
    database_url: str = "sqlite:///./lms.db"

    secret_key: str = "change-this-secret-key-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours
    minimum_attendance_minutes: float = 30

    video_provider: Literal["jaas", "jitsi"] = "jaas"
    jitsi_domain: str = "meet.jit.si"
    jaas_app_id: str = ""
    jaas_api_key_id: str = ""
    # Relative paths are resolved from backend/, never exposed to the browser.
    jaas_private_key_path: str = ""
    jaas_private_key: SecretStr = SecretStr("")
    jaas_token_expire_minutes: int = Field(default=60, ge=5, le=240)

    # Only emails on this domain can register - the "secure college
    # authentication" feature from the spec.
    allowed_email_domain: str = "hitam.org"
    # Public Google OAuth Web client ID. Empty keeps Google sign-in disabled.
    google_client_id: str = ""
    code_runner_url: str = "https://ce.judge0.com"
    code_runner_api_key: SecretStr = SecretStr("")
    code_runner_timeout_ms: int = Field(default=3000, ge=500, le=10000)

    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Operator-approved host -> institution email domain. Registration never enables DNS.
    institution_login_hosts: dict[str, str] = Field(default_factory=dict)

    @field_validator("institution_login_hosts")
    @classmethod
    def validate_login_hosts(cls, hosts):
        label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
        for host, domain in hosts.items():
            if (len(host) > 253 or not re.fullmatch(rf"{label}(?:\.{label})+", domain)
                    or host != f"ekeekrta.{domain}"):
                raise ValueError("Institution hosts must be lowercase ekeekrta.<institution-domain>, without a scheme, port or path")
        return hosts

    class Config:
        env_file = ".env"


settings = Settings()
