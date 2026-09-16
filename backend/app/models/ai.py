from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func

from app.database import Base


class AIAction(Base):
    __tablename__ = "ai_actions"

    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False, index=True)
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    intent = Column(String(50), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="draft", server_default="draft")
    prompt = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False, default=0.0)
    payload = Column(JSON, nullable=False, default=dict)
    preview = Column(JSON, nullable=False, default=dict)
    result = Column(JSON, nullable=True)
    requires_confirmation = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    executed_at = Column(DateTime(timezone=True), nullable=True)


class AIAuditLog(Base):
    __tablename__ = "ai_audit_logs"

    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    action_id = Column(Integer, ForeignKey("ai_actions.id"), nullable=True, index=True)
    event_type = Column(String(50), nullable=False)
    details = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AITrainingExample(Base):
    __tablename__ = "ai_training_examples"

    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False, index=True)
    submitted_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    command_text = Column(Text, nullable=False)
    original_intent = Column(String(50), nullable=False)
    corrected_intent = Column(String(50), nullable=False)
    corrected_payload = Column(JSON, nullable=False, default=dict)
    consented = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AICGPAGoal(Base):
    """One private, persistent academic goal per student."""

    __tablename__ = "ai_cgpa_goals"
    __table_args__ = (UniqueConstraint("institution_id", "student_id", name="uq_ai_cgpa_goal_student"),)

    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    current_cgpa = Column(Float, nullable=False)
    target_cgpa = Column(Float, nullable=False)
    completed_credits = Column(Float, nullable=False)
    remaining_credits = Column(Float, nullable=False)
    remaining_semesters = Column(Integer, nullable=False)
    weekly_study_hours = Column(Float, nullable=False)
    grading_scale_max = Column(Float, nullable=False)
    course_scenarios = Column(JSON, nullable=False, default=list)
    checkpoints = Column(JSON, nullable=False, default=list)
    data_source = Column(String(30), nullable=False, default="student", server_default="student")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AIKnowledgeSource(Base):
    """Faculty-approved text used by the local, course-scoped retrieval engine."""

    __tablename__ = "ai_knowledge_sources"

    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(180), nullable=False)
    source_type = Column(String(30), nullable=False, default="faculty_note", server_default="faculty_note")
    content = Column(Text, nullable=False)
    is_published = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    archived_at = Column(DateTime(timezone=True), nullable=True)


class AILectureContent(Base):
    """Private transcript and faculty-reviewed, extractive lecture output."""

    __tablename__ = "ai_lecture_contents"
    __table_args__ = (UniqueConstraint("session_id", name="uq_ai_lecture_session"),)

    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("class_sessions.id"), nullable=False, index=True)
    submitted_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    transcript = Column(Text, nullable=False)
    transcript_source = Column(String(30), nullable=False, default="faculty_text", server_default="faculty_text")
    summary = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="draft", server_default="draft")
    knowledge_source_id = Column(Integer, ForeignKey("ai_knowledge_sources.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AILectureRecording(Base):
    """Private local recording intake; media is never served by the public API."""

    __tablename__ = "ai_lecture_recordings"
    __table_args__ = (UniqueConstraint("session_id", name="uq_ai_lecture_recording_session"),)

    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("class_sessions.id"), nullable=False, index=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    original_filename = Column(String(180), nullable=False)
    content_type = Column(String(40), nullable=False)
    storage_key = Column(String(80), nullable=False, unique=True)
    size_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="uploaded", server_default="uploaded")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)


class AILecturePreparationJob(Base):
    """Audited private-worker request; it never contains raw media or transcripts."""

    __tablename__ = "ai_lecture_preparation_jobs"
    __table_args__ = (UniqueConstraint("recording_id", name="uq_ai_lecture_preparation_recording"),)

    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    recording_id = Column(Integer, ForeignKey("ai_lecture_recordings.id"), nullable=False, index=True)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="queued", server_default="queued", index=True)
    stage = Column(String(40), nullable=False, default="awaiting_private_worker",
                   server_default="awaiting_private_worker")
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    result = Column(JSON, nullable=True)
    error_code = Column(String(50), nullable=True)
    requested_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
