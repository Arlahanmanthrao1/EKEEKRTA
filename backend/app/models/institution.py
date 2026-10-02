import enum
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, String, ForeignKey, UniqueConstraint, func
from app.database import Base


class InstitutionType(str, enum.Enum):
    university = "university"
    training_institution = "training_institution"


class InstitutionStatus(str, enum.Enum):
    pending = "pending"
    active = "active"
    suspended = "suspended"
    rejected = "rejected"


class Institution(Base):
    __tablename__ = "institutions"
    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False)
    email = Column(String(254), nullable=True)
    email_domain = Column(String(253), unique=True, nullable=False)
    logo_url = Column(String(2048), nullable=True)
    address = Column(String(500), nullable=True)
    institution_type = Column(String(32), nullable=False, default=InstitutionType.university.value,
                              server_default=InstitutionType.university.value)
    default_theme = Column(String(20), nullable=False, default="light", server_default="light")
    grading_scale_max = Column(Float, nullable=False, default=10.0, server_default="10")
    passing_grade_point = Column(Float, nullable=False, default=4.0, server_default="4")
    status = Column(String(24), nullable=False, default=InstitutionStatus.active.value,
                    server_default=InstitutionStatus.active.value, index=True)
    status_reason = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False,
                        default=lambda: datetime.now(timezone.utc), server_default=func.now())
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True)


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("institution_id", "name"),)
    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
