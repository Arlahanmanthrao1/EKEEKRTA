from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator

from app.models.user import UserRole
from app.schemas.institution import InstitutionOut


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    department: str | None = Field(default=None, max_length=120)
    program: str | None = Field(default=None, max_length=120)
    batch: str | None = Field(default=None, min_length=2, max_length=40)
    semester_number: int | None = Field(default=None, ge=1, le=8)
    section: str | None = Field(default=None, max_length=40)
    institutional_id: str | None = Field(default=None, min_length=2, max_length=120)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Name must contain at least 2 characters")
        return value

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must fit within 72 UTF-8 bytes")
        return value

    @field_validator("email")
    @classmethod
    def validate_college_email(cls, v: str) -> str:
        v = v.lower()
        return v

    @field_validator("department", "program", "batch", "section", "institutional_id")
    @classmethod
    def clean_department(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: EmailStr
    role: UserRole
    department: str | None = None
    program: str | None = None
    batch: str | None = None
    semester_number: int | None = None
    section: str | None = None
    institutional_id: str | None = None
    institution_id: int | None = None
    institution: InstitutionOut | None = None


class UserSessionOut(UserOut):
    must_change_password: bool = False
