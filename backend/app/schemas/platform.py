from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


InstitutionStatusValue = Literal["pending", "active", "suspended", "rejected"]


class PlatformSummaryOut(BaseModel):
    institutions_total: int
    pending: int
    active: int
    suspended: int
    rejected: int
    universities: int
    training_institutions: int
    institution_users: int
    courses: int


class PlatformInstitutionOut(BaseModel):
    id: int
    name: str
    email: str | None = None
    email_domain: str
    logo_url: str | None = None
    address: str | None = None
    institution_type: str
    status: InstitutionStatusValue
    status_reason: str | None = None
    created_at: datetime | None = None
    reviewed_at: datetime | None = None
    user_count: int
    course_count: int
    administrator_count: int
    primary_administrator_name: str | None = None
    primary_administrator_email: str | None = None


class PlatformInstitutionStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    status: InstitutionStatusValue
    reason: str | None = Field(default=None, max_length=500)


class PlatformInstitutionDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    confirmation_name: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=5, max_length=500)


class PlatformInstitutionDeleteOut(BaseModel):
    deleted: bool = True
    institution_id: int
    institution_name: str
    deleted_user_count: int
    deleted_course_count: int


class PlatformAuditOut(BaseModel):
    id: int
    operator_id: int
    operator_name: str
    operator_email: str
    institution_id: int | None = None
    institution_name: str | None = None
    event_type: str
    details: dict[str, Any]
    created_at: datetime
