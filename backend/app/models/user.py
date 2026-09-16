import enum

from sqlalchemy import Boolean, Column, Integer, String, Enum, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.database import Base


class UserRole(str, enum.Enum):
    student = "student"
    faculty = "faculty"
    hod = "hod"
    admin = "admin"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("institution_id", "institutional_id", name="uq_user_institutional_id"),)

    id = Column(Integer, primary_key=True, index=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=True, index=True)
    institution = relationship("Institution")
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    must_change_password = Column(Boolean, nullable=False, default=False, server_default="false")
    erp_password_initialized = Column(Boolean, nullable=False, default=False, server_default="false")
    session_version = Column(Integer, nullable=False, default=0, server_default="0")
    role = Column(Enum(UserRole), nullable=False, default=UserRole.student)
    department = Column(String, nullable=True)
    program = Column(String, nullable=True)
    batch = Column(String, nullable=True)
    semester_number = Column(Integer, nullable=True)
    section = Column(String, nullable=True)
    # Stable identifier shared with the institution ERP (roll number,
    # admission number or employee number). Email remains a login identity,
    # not the cross-system primary key.
    institutional_id = Column(String(120), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    enrollments = relationship("Enrollment", back_populates="student")
    courses_taught = relationship("Course", back_populates="faculty")
