from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, func

from app.database import Base


class PlatformAuditLog(Base):
    """Immutable record of security-sensitive Ekeekrta operator actions."""

    __tablename__ = "platform_audit_logs"

    id = Column(Integer, primary_key=True)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=True, index=True)
    event_type = Column(String(80), nullable=False, index=True)
    details = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
