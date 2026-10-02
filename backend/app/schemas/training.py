from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


BatchStatus = Literal["planned", "active", "completed", "archived"]


class TrainingBatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    course_id: int = Field(gt=0)
    trainer_id: int | None = Field(default=None, gt=0)
    name: str = Field(min_length=2, max_length=160)
    code: str = Field(min_length=2, max_length=80)
    start_date: date
    end_date: date
    status: BatchStatus = "planned"
    capacity: int = Field(default=30, ge=1, le=10000)
    recording_drive_folder_id: str | None = Field(default=None, min_length=10, max_length=180)
    certificate_enabled: bool = True
    certificate_min_progress: float = Field(default=80, ge=0, le=100)
    certificate_min_attendance: float = Field(default=75, ge=0, le=100)

    @model_validator(mode="after")
    def dates_are_ordered(self):
        if self.end_date < self.start_date:
            raise ValueError("Batch end date must be on or after its start date")
        return self


class TrainingBatchUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    trainer_id: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    start_date: date | None = None
    end_date: date | None = None
    status: BatchStatus | None = None
    capacity: int | None = Field(default=None, ge=1, le=10000)
    recording_drive_folder_id: str | None = Field(default=None, min_length=10, max_length=180)
    certificate_enabled: bool | None = None
    certificate_min_progress: float | None = Field(default=None, ge=0, le=100)
    certificate_min_attendance: float | None = Field(default=None, ge=0, le=100)


class TrainingBatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    institution_id: int
    course_id: int
    trainer_id: int
    name: str
    code: str
    start_date: date
    end_date: date
    status: BatchStatus
    capacity: int
    certificate_enabled: bool
    certificate_min_progress: float
    certificate_min_attendance: float
    recording_drive_folder_configured: bool = False
    created_at: datetime
    course_name: str | None = None
    course_code: str | None = None
    trainer_name: str | None = None
    learner_count: int = 0


class BatchEnrollmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    student_id: int = Field(gt=0)


class BatchEnrollmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    batch_id: int
    student_id: int
    status: str
    enrolled_at: datetime
    completed_at: datetime | None = None
    student_name: str | None = None
    student_email: str | None = None
    institutional_id: str | None = None


class TrainingModuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    position: int | None = Field(default=None, ge=1, le=10000)
    published: bool = False


class TrainingModuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    position: int | None = Field(default=None, ge=1, le=10000)
    published: bool | None = None


class TrainingLessonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    resource_url: HttpUrl | None = None
    position: int | None = Field(default=None, ge=1, le=10000)
    estimated_minutes: int = Field(default=30, ge=1, le=1440)
    required: bool = True


class TrainingLessonUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    resource_url: HttpUrl | None = None
    position: int | None = Field(default=None, ge=1, le=10000)
    estimated_minutes: int | None = Field(default=None, ge=1, le=1440)
    required: bool | None = None


class TrainingOrderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ordered_ids: list[int] = Field(min_length=1, max_length=1000)


class TrainingLessonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    module_id: int
    title: str
    description: str | None
    resource_url: str | None
    position: int
    estimated_minutes: int
    required: bool
    completed: bool = False


class TrainingModuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    batch_id: int
    title: str
    description: str | None
    position: int
    published: bool
    lessons: list[TrainingLessonOut] = Field(default_factory=list)


class CertificateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    batch_id: int
    student_id: int
    certificate_number: str
    issued_at: datetime
    eligibility_snapshot: dict
    revoked_at: datetime | None
    learner_name: str | None = None
    batch_name: str | None = None
    course_name: str | None = None
    institution_name: str | None = None
