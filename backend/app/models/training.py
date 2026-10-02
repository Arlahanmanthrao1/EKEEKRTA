from sqlalchemy import (Boolean, Column, Date, DateTime, Float, ForeignKey, Integer,
                        JSON, String, Text, UniqueConstraint, func)
from sqlalchemy.orm import relationship

from app.database import Base


class TrainingBatch(Base):
    __tablename__ = "training_batches"
    __table_args__ = (UniqueConstraint("institution_id", "code", name="uq_training_batch_code"),)

    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    trainer_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    code = Column(String(80), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String(24), nullable=False, default="planned", server_default="planned", index=True)
    capacity = Column(Integer, nullable=False, default=30, server_default="30")
    recording_drive_folder_id = Column(String(180), nullable=True)
    certificate_enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    certificate_min_progress = Column(Float, nullable=False, default=80, server_default="80")
    certificate_min_attendance = Column(Float, nullable=False, default=75, server_default="75")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    institution = relationship("Institution")
    course = relationship("Course")
    trainer = relationship("User", foreign_keys=[trainer_id])
    memberships = relationship("TrainingBatchEnrollment", back_populates="batch")
    modules = relationship("TrainingModule", back_populates="batch", order_by="TrainingModule.position")

    @property
    def recording_drive_folder_configured(self):
        return bool(self.recording_drive_folder_id)


class TrainingBatchEnrollment(Base):
    __tablename__ = "training_batch_enrollments"
    __table_args__ = (UniqueConstraint("batch_id", "student_id", name="uq_training_batch_student"),)

    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey("training_batches.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="active", server_default="active")
    enrolled_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    batch = relationship("TrainingBatch", back_populates="memberships")
    student = relationship("User")


class TrainingModule(Base):
    __tablename__ = "training_modules"
    __table_args__ = (UniqueConstraint("batch_id", "position", name="uq_training_module_position"),)

    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey("training_batches.id"), nullable=False, index=True)
    title = Column(String(180), nullable=False)
    description = Column(Text, nullable=True)
    position = Column(Integer, nullable=False)
    published = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    batch = relationship("TrainingBatch", back_populates="modules")
    lessons = relationship("TrainingLesson", back_populates="module", order_by="TrainingLesson.position")


class TrainingLesson(Base):
    __tablename__ = "training_lessons"
    __table_args__ = (UniqueConstraint("module_id", "position", name="uq_training_lesson_position"),)

    id = Column(Integer, primary_key=True)
    module_id = Column(Integer, ForeignKey("training_modules.id"), nullable=False, index=True)
    title = Column(String(180), nullable=False)
    description = Column(Text, nullable=True)
    resource_url = Column(String(2048), nullable=True)
    position = Column(Integer, nullable=False)
    estimated_minutes = Column(Integer, nullable=False, default=30, server_default="30")
    required = Column(Boolean, nullable=False, default=True, server_default="true")

    module = relationship("TrainingModule", back_populates="lessons")
    completions = relationship("TrainingLessonCompletion", back_populates="lesson")


class TrainingLessonCompletion(Base):
    __tablename__ = "training_lesson_completions"
    __table_args__ = (UniqueConstraint("lesson_id", "student_id", name="uq_training_lesson_student"),)

    id = Column(Integer, primary_key=True)
    lesson_id = Column(Integer, ForeignKey("training_lessons.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    completed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    lesson = relationship("TrainingLesson", back_populates="completions")
    student = relationship("User")


class TrainingCertificate(Base):
    __tablename__ = "training_certificates"
    __table_args__ = (UniqueConstraint("batch_id", "student_id", name="uq_training_certificate_student"),)

    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey("training_batches.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    certificate_number = Column(String(80), nullable=False, unique=True, index=True)
    issued_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    issued_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    eligibility_snapshot = Column(JSON, nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    batch = relationship("TrainingBatch")
    student = relationship("User", foreign_keys=[student_id])
    issuer = relationship("User", foreign_keys=[issued_by])
