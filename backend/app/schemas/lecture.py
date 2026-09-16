from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LectureTranscriptIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    transcript: str = Field(min_length=180, max_length=100000)
    # Automatic server ingestion is deliberately not exposed to browser callers.
    transcript_source: Literal["faculty_text"] = "faculty_text"
    permissions_confirmed: bool

    @model_validator(mode="after")
    def require_permission(self):
        if not self.permissions_confirmed:
            raise ValueError("Confirm that the lecture text may be processed and sensitive details were removed")
        return self


class LectureContentOut(BaseModel):
    id: int
    course_id: int
    session_id: int
    status: str
    transcript_source: str
    summary: dict
    transcript: str | None = None
    created_at: datetime
    updated_at: datetime


class LecturePublicationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publish: bool


class LectureReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    included_statement_numbers: list[int] = Field(min_length=1, max_length=6)
    included_topics: list[str] = Field(default_factory=list, max_length=8)


class LectureRecordingOut(BaseModel):
    id: int
    course_id: int
    session_id: int
    original_filename: str
    content_type: str
    size_bytes: int
    status: str
    notes_status: str | None = None
    preparation: "LectureRecordingPreparationOut | None" = None
    created_at: datetime


class LectureRecordingPreparationOut(BaseModel):
    id: int
    recording_id: int
    status: str
    stage: str
    attempts: int
    error_code: str | None = None
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class LectureRecordingCapabilitiesOut(BaseModel):
    local_upload_available: bool
    preparation_queue_available: bool
    maximum_upload_mb: int
    automatic_recording_available: bool = False
    automatic_transcription_available: bool = False
    slide_ocr_available: bool = False


LectureRecordingOut.model_rebuild()
