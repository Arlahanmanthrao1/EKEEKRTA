from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.database import Base


class DataExchangeProfile(Base):
    """Reusable university export mapping owned by one faculty account."""

    __tablename__ = "data_exchange_profiles"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_data_exchange_owner_name"),)

    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    target_platform = Column(String(120), nullable=False)
    data_type = Column(String(40), nullable=False)
    template_headers = Column(JSON, nullable=False)
    mapping = Column(JSON, nullable=False)
    export_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    institution = relationship("Institution")
    owner = relationship("User")
