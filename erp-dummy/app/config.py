from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./erp.db"
    erp_api_token: SecretStr = SecretStr("")
    erp_institution_id: str = ""
    erp_name: str = "College ERP Sandbox"
    recent_record_limit: int = Field(default=100, ge=10, le=500)

    class Config:
        env_file = ".env"


settings = Settings()
