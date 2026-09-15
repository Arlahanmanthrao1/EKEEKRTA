from datetime import datetime
import os

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator, model_validator


class ERPConfigurationIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    base_url: HttpUrl
    api_token: str | None = Field(default=None, min_length=16, max_length=4096)
    external_institution_id: str | None = Field(default=None, max_length=160)
    enabled: bool = False
    sync_students: bool = True
    sync_courses: bool = True
    sync_attendance: bool = True

    @field_validator("base_url")
    @classmethod
    def require_secure_erp_url(cls, value: HttpUrl):
        local_development = not os.getenv("VERCEL") and value.scheme == "http" and value.host in {"localhost", "127.0.0.1", "::1"}
        if value.scheme != "https" and not local_development:
            raise ValueError("ERP endpoint must use HTTPS")
        if value.username or value.password or value.query or value.fragment:
            raise ValueError("ERP endpoint must not contain credentials, a query or a fragment")
        return value


class ERPConfigurationOut(BaseModel):
    configured: bool
    base_url: str | None = None
    external_institution_id: str | None = None
    token_configured: bool = False
    enabled: bool = False
    sync_students: bool = True
    sync_courses: bool = True
    sync_attendance: bool = True
    last_tested_at: datetime | None = None
    last_test_success: bool | None = None
    last_test_message: str | None = None


class ERPSyncEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    entity_key: str
    status: str
    revision: int
    attempts: int
    response_code: int | None = None
    last_error: str | None = None
    created_at: datetime
    synced_at: datetime | None = None
    updated_at: datetime


class ERPSyncResult(BaseModel):
    queued: int = 0
    synced: int = 0
    failed: int = 0
    pending: int = 0
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    message: str


class ERPStudentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    institutional_id: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    department: str = Field(min_length=1, max_length=120)
    program: str = Field(min_length=1, max_length=120)
    batch: str = Field(min_length=2, max_length=40)
    semester_number: int = Field(ge=1, le=8)
    section: str = Field(min_length=1, max_length=40)


class ERPStudentExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    institution_id: str | None = None
    students: list[ERPStudentRecord]


class ERPStudentImportResult(BaseModel):
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    message: str


class ERPUserRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: Literal["student", "faculty", "hod", "admin"]
    institutional_id: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    department: str | None = Field(default=None, max_length=120)
    program: str | None = Field(default=None, max_length=120)
    batch: str | None = Field(default=None, max_length=40)
    semester_number: int | None = Field(default=None, ge=1, le=8)
    section: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def validate_role_fields(self):
        if self.role in {"student", "faculty", "hod"} and not self.department:
            raise ValueError(f"{self.role.title()} records require a department")
        if self.role == "student" and not all((self.program, self.batch, self.semester_number, self.section)):
            raise ValueError("Student records require program, batch, semester and section")
        return self


class ERPUserExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    institution_id: str | None = None
    users: list[ERPUserRecord] = Field(max_length=2000)


class ERPUserPreviewRecord(BaseModel):
    row: int
    role: str
    institutional_id: str
    name: str
    email: EmailStr
    department: str | None = None
    action: Literal["create", "update", "skip"]
    reason: str | None = None


class ERPUserImportPreviewOut(BaseModel):
    confirmation_token: str
    expires_in_minutes: int
    total: int
    creates: int
    updates: int
    skipped: int
    role_counts: dict[str, int]
    records: list[ERPUserPreviewRecord]


class ERPUserImportConfirmIn(BaseModel):
    confirmation_token: str = Field(min_length=40, max_length=4096)


class ERPUserImportResult(BaseModel):
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    role_counts: dict[str, int] = Field(default_factory=dict)
    message: str
