from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CourseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str
    code: str
    department: str | None = None
    semester: str | None = None
    course_type: Literal["academic", "non_academic"] = "academic"
    program: str | None = Field(default=None, max_length=120)
    batch: str | None = Field(default=None, max_length=40)
    semester_number: int | None = Field(default=None, ge=1, le=8)
    section: str | None = Field(default=None, max_length=40)
    enrollment_mode: Literal["compulsory", "elective"] = "elective"
    credits: float | None = Field(default=None, gt=0, le=50)

    @model_validator(mode="after")
    def require_academic_cohort(self):
        if self.course_type == "academic" and (not self.program or not self.batch or self.semester_number is None):
            raise ValueError("Academic courses require program, batch and semester")
        return self


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    department: str | None = None
    semester: str | None = None
    course_type: Literal["academic", "non_academic"]
    program: str | None = None
    batch: str | None = None
    semester_number: int | None = None
    section: str | None = None
    enrollment_mode: Literal["compulsory", "elective"]
    credits: float | None = None
    faculty_id: int | None = None


class CourseCreditsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credits: float = Field(gt=0, le=50)


class EnrollmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    course_id: int
