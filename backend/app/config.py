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
    # Local/college recording intake only; Vercel uploads are disabled.
    recording_storage_dir: str = "private-recordings"
    recording_max_upload_mb: int = Field(default=250, ge=1, le=1000)
    # Host path mapped to Jibri's finalized /storage recordings directory.
    jibri_recordings_dir: str = ""
    jibri_recording_max_mb: int = Field(default=10000, ge=100, le=50000)
    # Zero disables expiry; an institution must explicitly approve a policy.
    recording_retention_days: int = Field(default=0, ge=0, le=3650)
    # Optional institution-built model executables. Empty means unavailable;
    # there is deliberately no cloud or public-model fallback.
    native_speech_model_executable: str = ""
    native_speech_model_id: str = ""
    native_slide_ocr_executable: str = ""
    native_slide_ocr_model_id: str = ""
    native_model_timeout_minutes: int = Field(default=120, ge=1, le=720)

    video_provider: Literal["jaas", "jitsi"] = "jaas"
    jitsi_domain: str = "meet.jit.si"
    jitsi_jwt_app_id: str = ""
    jitsi_jwt_app_secret: SecretStr = SecretStr("")
    jitsi_jwt_expire_minutes: int = Field(default=60, ge=5, le=240)
    # Enable only after the college Jitsi deployment has a working Jibri pool.
    jitsi_auto_recording_enabled: bool = False
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
    # Password recovery is disabled until an institution/operator configures
    # an SMTP sender. Reset tokens are short-lived and only their hashes are stored.
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from_email: str = ""
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    password_reset_base_url: str = "http://127.0.0.1:5173"
    password_reset_expire_minutes: int = Field(default=30, ge=5, le=120)
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
