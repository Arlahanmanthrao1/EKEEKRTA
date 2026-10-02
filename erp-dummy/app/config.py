from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./erp.db"
    erp_api_token: SecretStr = SecretStr("")
    erp_institution_id: str = ""
    erp_name: str = "College ERP Sandbox"
    recent_record_limit: int = Field(default=100, ge=10, le=500)
    whatsapp_notifications_enabled: bool = False
    whatsapp_graph_api_version: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: SecretStr = SecretStr("")
    whatsapp_absence_template_name: str = "class_absence_alert"
    whatsapp_template_language: str = "en_US"
    whatsapp_request_timeout_seconds: float = Field(default=10, ge=2, le=30)
    whatsapp_max_attempts: int = Field(default=3, ge=1, le=10)

    class Config:
        env_file = ".env"


settings = Settings()
