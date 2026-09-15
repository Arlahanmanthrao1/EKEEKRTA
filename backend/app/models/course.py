from sqlalchemy import Column, Float, Integer, String, ForeignKey, DateTime, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.database import Base


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = (UniqueConstraint("institution_id", "code", name="uq_courses_institution_code"),)

    id = Column(Integer, primary_key=True, index=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=True, index=True)
    name = Column(String, nullable=False)
    code = Column(String, nullable=False)
    department = Column(String, nullable=True)
    semester = Column(String, nullable=True)
    course_type = Column(String, nullable=False, default="academic", server_default="academic")
    program = Column(String, nullable=True)
    batch = Column(String, nullable=True)
    semester_number = Column(Integer, nullable=True)
    section = Column(String, nullable=True)
    enrollment_mode = Column(String, nullable=False, default="elective", server_default="elective")
    credits = Column(Float, nullable=True)
    faculty_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    faculty = relationship("User", back_populates="courses_taught")
    enrollments = relationship("Enrollment", back_populates="course")


class Enrollment(Base):
    __tablename__ = "enrollments"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    enrolled_at = Column(DateTime(timezone=True), server_default=func.now())

    student = relationship("User", back_populates="enrollments")
    course = relationship("Course", back_populates="enrollments")
