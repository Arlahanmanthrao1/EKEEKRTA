from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AssignmentCreate(BaseModel):
    course_id: int
    title: str
    description: str | None = None
    due_date: datetime | None = None
    max_marks: float = 100.0


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    course_id: int
    title: str
    description: str | None = None
    due_date: datetime | None = None
    max_marks: float


class SubmissionCreate(BaseModel):
    assignment_id: int
    file_url: str


class SubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    assignment_id: int
    student_id: int
    file_url: str | None = None
    marks_obtained: float | None = None
