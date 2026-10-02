from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, UniqueConstraint, func

from app.database import Base


class Student(Base):
    """ERP identity directory. The historic table name is kept to preserve data."""
    __tablename__ = "erp_students"
    __table_args__ = (UniqueConstraint("institution_external_id", "institutional_id"),)

    id = Column(Integer, primary_key=True, index=True)
    institution_external_id = Column(String(160), nullable=True, index=True)
    ekeekrta_id = Column(Integer, nullable=False)
    institutional_id = Column(String(120), nullable=False)
    role = Column(String(20), nullable=False, default="student", server_default="student")
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    department = Column(String, nullable=True)
    program = Column(String, nullable=True)
    batch = Column(String, nullable=True)
    semester_number = Column(Integer, nullable=True)
    section = Column(String, nullable=True)
    parent_phone = Column(String(16), nullable=True)
    parent_whatsapp_opt_in = Column(Boolean, nullable=False, default=False, server_default="false")
    synced_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Course(Base):
    __tablename__ = "erp_courses"
    __table_args__ = (UniqueConstraint("institution_external_id", "code"),)

    id = Column(Integer, primary_key=True)
    institution_external_id = Column(String(160), nullable=True, index=True)
    ekeekrta_id = Column(Integer, nullable=False)
    code = Column(String(120), nullable=False)
    name = Column(String(240), nullable=False)
    department = Column(String(120), nullable=True)
    course_type = Column(String(40), nullable=True)
    program = Column(String(120), nullable=True)
    batch = Column(String(40), nullable=True)
    semester_number = Column(Integer, nullable=True)
    section = Column(String(40), nullable=True)
    enrollment_mode = Column(String(40), nullable=True)
    credits = Column(Float, nullable=True)
    faculty_institutional_id = Column(String(120), nullable=True)
    faculty_name = Column(String(160), nullable=True)
    synced_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AttendanceRecord(Base):
    __tablename__ = "erp_attendance_records"
    __table_args__ = (UniqueConstraint("institution_external_id", "ekeekrta_id"),)

    id = Column(Integer, primary_key=True, index=True)
    institution_external_id = Column(String(160), nullable=True, index=True)
    ekeekrta_id = Column(Integer, nullable=False)
    student_institutional_id = Column(String(120), nullable=False, index=True)
    student_name = Column(String(160), nullable=False)
    course_code = Column(String(120), nullable=False)
    course_name = Column(String(240), nullable=False)
    class_session_id = Column(Integer, nullable=False)
    duration_minutes = Column(Float, default=0.0)
    present = Column(Boolean, default=False)
    session_started_at = Column(DateTime(timezone=True), nullable=True)
    session_ended_at = Column(DateTime(timezone=True), nullable=True)
    source = Column(String(20), nullable=False, default="online", server_default="online")
    synced_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OfflineClassSession(Base):
    __tablename__ = "erp_offline_class_sessions"
    __table_args__ = (
        UniqueConstraint("institution_external_id", "submission_id"),
        UniqueConstraint("institution_external_id", "course_code", "held_at"),
    )

    id = Column(Integer, primary_key=True)
    institution_external_id = Column(String(160), nullable=True, index=True)
    submission_id = Column(String(36), nullable=False)
    course_code = Column(String(120), nullable=False, index=True)
    course_name = Column(String(240), nullable=False)
    faculty_institutional_id = Column(String(120), nullable=False, index=True)
    faculty_name = Column(String(160), nullable=False)
    held_at = Column(DateTime(timezone=True), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    finalized_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SyncReceipt(Base):
    __tablename__ = "erp_sync_receipts"

    id = Column(Integer, primary_key=True)
    idempotency_key = Column(String(200), nullable=False, unique=True, index=True)
    event_type = Column(String(40), nullable=False)
    received_at = Column(DateTime(timezone=True), server_default=func.now())


class AcademicResult(Base):
    __tablename__ = "erp_academic_results"
    __table_args__ = (UniqueConstraint("institution_external_id", "student_institutional_id"),)

    id = Column(Integer, primary_key=True)
    institution_external_id = Column(String(160), nullable=True, index=True)
    student_institutional_id = Column(String(120), nullable=False, index=True)
    current_cgpa = Column(Float, nullable=False)
    completed_credits = Column(Float, nullable=False)
    remaining_credits = Column(Float, nullable=False)
    grading_scale_max = Column(Float, nullable=False, default=10.0, server_default="10")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WhatsAppNotification(Base):
    __tablename__ = "erp_whatsapp_notifications"
    __table_args__ = (UniqueConstraint("attendance_record_id", "notification_type"),)

    id = Column(Integer, primary_key=True)
    institution_external_id = Column(String(160), nullable=True, index=True)
    attendance_record_id = Column(Integer, nullable=False, index=True)
    notification_type = Column(String(40), nullable=False, default="class_absence",
                               server_default="class_absence")
    attendance_source = Column(String(20), nullable=False, default="online", server_default="online")
    student_institutional_id = Column(String(120), nullable=False, index=True)
    parent_phone_last4 = Column(String(4), nullable=True)
    status = Column(String(32), nullable=False, default="pending", server_default="pending")
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    provider_message_id = Column(String(240), nullable=True)
    last_error = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    sent_at = Column(DateTime(timezone=True), nullable=True)
