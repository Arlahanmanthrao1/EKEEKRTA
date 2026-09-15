import base64
import binascii
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, TypeAdapter, ValidationError, field_validator, model_validator


HTTPS_URL = TypeAdapter(HttpUrl)
LOGO_DATA = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})$")


class InstitutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str | None = None
    email_domain: str
    logo_url: str | None = None
    address: str | None = None
    default_theme: Literal["light", "dark", "system"] = "light"
    grading_scale_max: float = 10
    passing_grade_point: float = 4


class InstitutionThemeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_theme: Literal["light", "dark", "system"]


class InstitutionGradingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grading_scale_max: float = Field(ge=4, le=100)
    passing_grade_point: float = Field(ge=0)

    @model_validator(mode="after")
    def passing_fits_scale(self):
        if self.passing_grade_point > self.grading_scale_max:
            raise ValueError("Passing grade point cannot exceed the grading-scale maximum")
        return self


class InstitutionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    logo_url: str | None = Field(default=None, max_length=2048)
    address: str | None = Field(default=None, max_length=500)

    @field_validator("logo_url")
    @classmethod
    def https_logo(cls, value):
        if not value:
            return value
        uploaded = LOGO_DATA.fullmatch(value)
        if uploaded:
            try:
                image = base64.b64decode(uploaded.group(2), validate=True)
            except (binascii.Error, ValueError):
                raise ValueError("Uploaded logo data is invalid") from None
            kind = uploaded.group(1)
            valid_signature = (
                kind == "png" and image.startswith(b"\x89PNG\r\n\x1a\n")
                or kind == "jpeg" and image.startswith(b"\xff\xd8\xff")
                or kind == "webp" and len(image) >= 12 and image[:4] == b"RIFF" and image[8:12] == b"WEBP"
            )
            if not valid_signature:
                raise ValueError("Uploaded logo does not match its image type")
            return value
        try:
            parsed = HTTPS_URL.validate_python(value)
        except ValidationError:
            raise ValueError("Upload a PNG, JPEG, or WebP logo, or use an HTTPS logo link") from None
        if parsed.scheme != "https":
            raise ValueError("Use an HTTPS logo link")
        return str(parsed)


class DepartmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=120)


class DepartmentOut(DepartmentCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
