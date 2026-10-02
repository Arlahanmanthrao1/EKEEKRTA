from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float, Boolean, func
from sqlalchemy.orm import relationship

from app.database import Base


class ClassSession(Base):
    __tablename__ = "class_sessions"

    id = Column(Integer, primary_key=True, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    training_batch_id = Column(Integer, ForeignKey("training_batches.id"), nullable=True, index=True)
    jitsi_room_id = Column(String, nullable=False, unique=True)
    scheduled_at = Column(DateTime(timezone=True), server_default=func.now())
    recording_url = Column(String, nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    # Controls whether students are pushed into fullscreen on join. Faculty
    # can flip this off mid-class - see PATCH /attendance/sessions/{id}/fullscreen.
    fullscreen_required = Column(Boolean, default=True, nullable=False)

    course = relationship("Course")
    training_batch = relationship("TrainingBatch")
    attendance_records = relationship("Attendance", back_populates="session")


class Attendance(Base):
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("class_sessions.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    duration_minutes = Column(Float, default=0.0)
    present = Column(Boolean, default=False)
    # Set on a "joined" event, cleared on the matching "left" event - lets
    # us compute a real elapsed duration instead of guessing.
    last_joined_at = Column(DateTime(timezone=True), nullable=True)

    session = relationship("ClassSession", back_populates="attendance_records")
    student = relationship("User")
