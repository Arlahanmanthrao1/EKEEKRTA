from sqlalchemy import Column, Float, Integer, String, ForeignKey, UniqueConstraint
from app.database import Base


class Institution(Base):
    __tablename__ = "institutions"
    id = Column(Integer, primary_key=True)
    name = Column(String(160), nullable=False)
    email = Column(String(254), nullable=True)
    email_domain = Column(String(253), unique=True, nullable=False)
    logo_url = Column(String(2048), nullable=True)
    address = Column(String(500), nullable=True)
    default_theme = Column(String(20), nullable=False, default="light", server_default="light")
    grading_scale_max = Column(Float, nullable=False, default=10.0, server_default="10")
    passing_grade_point = Column(Float, nullable=False, default=4.0, server_default="4")


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("institution_id", "name"),)
    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
