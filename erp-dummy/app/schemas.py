from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class InstitutionRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ekeekrta_id: int
    external_id: str | None = Field(default=None, max_length=160)
    name: str
    email_domain: str


class StudentData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ekeekrta_id: int
    institutional_id: str = Field(min_length=2, max_length=120)
    name: str
    email: EmailStr
    department: str | None = None
    program: str | None = None
    batch: str | None = None
    semester_number: int | None = Field(default=None, ge=1, le=8)
    section: str | None = None


class ERPStudentCreate(BaseModel):
    """Student master data entered in the ERP before an EKEEKRTA account exists."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    institutional_id: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    department: str = Field(min_length=1, max_length=120)
    program: str = Field(min_length=1, max_length=120)
    batch: str = Field(min_length=2, max_length=40)
    semester_number: int = Field(ge=1, le=8)
    section: str = Field(min_length=1, max_length=40)


class ERPUserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: Literal["student", "faculty", "hod"]
    institutional_id: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    department: str = Field(min_length=1, max_length=120)
    program: str | None = Field(default=None, max_length=120)
    batch: str | None = Field(default=None, max_length=40)
    semester_number: int | None = Field(default=None, ge=1, le=8)
    section: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def require_student_cohort(self):
        if self.role == "student" and not all((self.program, self.batch, self.semester_number, self.section)):
            raise ValueError("Students require program, batch, semester and section")
        return self


class StudentSyncIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["student.upsert"]
    institution: InstitutionRef
    student: StudentData
    occurred_at: datetime


class FacultyRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ekeekrta_id: int
    institutional_id: str | None = None
    name: str
    email: EmailStr


class CourseData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ekeekrta_id: int
    code: str
    name: str
    department: str | None = None
    course_type: str | None = None
    program: str | None = None
    batch: str | None = None
    semester_number: int | None = Field(default=None, ge=1, le=8)
    section: str | None = None
    enrollment_mode: str | None = None
    credits: float | None = Field(default=None, gt=0, le=50)
    faculty: FacultyRef | None = None


class ERPResultUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    student_institutional_id: str = Field(min_length=2, max_length=120)
    current_cgpa: float = Field(ge=0)
    completed_credits: float = Field(gt=0, le=1000)
    remaining_credits: float = Field(gt=0, le=1000)
    grading_scale_max: float = Field(default=10, ge=4, le=100)

    @model_validator(mode="after")
    def cgpa_fits_scale(self):
        if self.current_cgpa > self.grading_scale_max:
            raise ValueError("Current CGPA cannot exceed the grading-scale maximum")
        return self


class CourseSyncIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["course.upsert"]
    institution: InstitutionRef
    course: CourseData
    occurred_at: datetime


class AttendanceStudent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ekeekrta_id: int
    institutional_id: str = Field(min_length=2, max_length=120)
    email: EmailStr
    name: str


class AttendanceCourse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ekeekrta_id: int
    code: str
    name: str


class SessionData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ekeekrta_id: int
    scheduled_at: datetime | None = None
    ended_at: datetime | None = None


class AttendanceData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ekeekrta_id: int
    duration_minutes: float = Field(ge=0, le=1440)
    present: bool


class AttendanceSyncIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["attendance.upsert"]
    institution: InstitutionRef
    student: AttendanceStudent
    course: AttendanceCourse
    class_session: SessionData
    attendance: AttendanceData
    occurred_at: datetime
