from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


AI_INTENTS = ("schedule_class", "draft_assignment", "draft_quiz", "student_progress", "import_erp_students",
              "create_department", "create_course", "bulk_create_accounts", "cgpa_plan", "course_question", "help")


class AICommandIn(BaseModel):
    command: str = Field(min_length=3, max_length=2000)
    course_id: int | None = None
    student_id: int | None = None
    timezone: str = Field(default="Asia/Kolkata", max_length=80)


class AIActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    intent: str
    status: str
    prompt: str
    confidence: float
    payload: dict[str, Any]
    preview: dict[str, Any]
    result: dict[str, Any] | None = None
    requires_confirmation: bool
    created_at: datetime
    executed_at: datetime | None = None


class AICommandOut(BaseModel):
    message: str
    action: AIActionOut


class AICorrectionIn(BaseModel):
    corrected_intent: str
    corrected_payload: dict[str, Any] = Field(default_factory=dict)
    consent: bool


class AICapabilitiesOut(BaseModel):
    engine: str
    external_models: bool
    capabilities: list[dict[str, Any]]


class AIBulkAccountRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: Literal["student", "faculty"]
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    institutional_id: str = Field(min_length=2, max_length=120)
    department: str = Field(min_length=2, max_length=120)
    program: str | None = Field(default=None, max_length=120)
    batch: str | None = Field(default=None, max_length=40)
    semester_number: int | None = Field(default=None, ge=1, le=8)
    section: str | None = Field(default=None, max_length=40)

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, value):
        return str(value).lower()


class AIBulkAccountsIn(BaseModel):
    records: list[AIBulkAccountRecord] = Field(min_length=1, max_length=250)


class AIContentDraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    course_id: int
    content_type: Literal["assignment", "quiz"]
    topic: str = Field(min_length=3, max_length=160)
    source_text: str = Field(min_length=80, max_length=12000)
    question_count: int = Field(default=5, ge=1, le=20)
    max_marks: float = Field(default=100, gt=0, le=1000)
    due_date: datetime | None = None


class AIKnowledgeSourceIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    course_id: int
    title: str = Field(min_length=3, max_length=180)
    source_type: Literal["faculty_note", "syllabus", "lecture", "reference", "other"] = "faculty_note"
    content: str = Field(min_length=80, max_length=50000)
    publish_to_students: bool = True


class AIKnowledgePublicationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    published: bool


class AICourseQuestionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    course_id: int
    question: str = Field(min_length=3, max_length=500)


class AICourseScenarioIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    course_id: int
    expected_grade_point: float = Field(ge=0)


class AICGPAPlanIn(BaseModel):
    """Student-provided official values used only for an explainable projection."""

    model_config = ConfigDict(extra="forbid")

    grading_scale_max: float = Field(default=10, ge=4, le=100)
    current_cgpa: float = Field(ge=0)
    target_cgpa: float = Field(gt=0)
    completed_credits: float = Field(gt=0, le=1000)
    remaining_credits: float = Field(gt=0, le=1000)
    remaining_semesters: int = Field(ge=1, le=16)
    weekly_study_hours: float = Field(gt=0, le=112)
    course_scenarios: list[AICourseScenarioIn] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def values_fit_scale(self):
        if self.current_cgpa > self.grading_scale_max:
            raise ValueError("Current CGPA cannot exceed the grading-scale maximum")
        if self.target_cgpa > self.grading_scale_max:
            raise ValueError("Target CGPA cannot exceed the grading-scale maximum")
        if len({item.course_id for item in self.course_scenarios}) != len(self.course_scenarios):
            raise ValueError("Each course can appear only once in a grade scenario")
        return self
