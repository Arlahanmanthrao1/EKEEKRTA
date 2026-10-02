from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MappingRule(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source: str = Field(min_length=1, max_length=80)
    transform: str = Field(default="none", max_length=40)


class DataExchangeProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=120)
    target_platform: str = Field(min_length=2, max_length=120)
    data_type: str = Field(min_length=2, max_length=40)
    template_headers: list[str] = Field(min_length=1, max_length=200)
    mapping: dict[str, MappingRule]

    @model_validator(mode="after")
    def validate_template(self):
        normalized = [header.strip() for header in self.template_headers]
        if any(not header for header in normalized):
            raise ValueError("Template headers cannot be empty")
        if len({header.lower() for header in normalized}) != len(normalized):
            raise ValueError("Template headers must be unique")
        if set(self.mapping) - set(normalized):
            raise ValueError("Mappings must belong to the uploaded template")
        self.template_headers = normalized
        return self


class DataExchangeProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    target_platform: str
    data_type: str
    template_headers: list[str]
    mapping: dict
    export_count: int
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime
