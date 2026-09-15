from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func

from app.database import Base


class ERPIntegration(Base):
    __tablename__ = "erp_integrations"

    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False, unique=True, index=True)
    base_url = Column(String(2048), nullable=False)
    external_institution_id = Column(String(160), nullable=True)
    encrypted_api_token = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, default=False)
    sync_students = Column(Boolean, nullable=False, default=True)
    sync_courses = Column(Boolean, nullable=False, default=True)
    sync_attendance = Column(Boolean, nullable=False, default=True)
    last_tested_at = Column(DateTime(timezone=True), nullable=True)
    last_test_success = Column(Boolean, nullable=True)
    last_test_message = Column(String(500), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ERPSyncEvent(Base):
    __tablename__ = "erp_sync_events"
    __table_args__ = (UniqueConstraint("institution_id", "event_type", "entity_key", name="uq_erp_sync_entity"),)

    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False, index=True)
    event_type = Column(String(40), nullable=False)
    entity_key = Column(String(160), nullable=False)
    payload_json = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    revision = Column(Integer, nullable=False, default=1)
    attempts = Column(Integer, nullable=False, default=0)
    response_code = Column(Integer, nullable=True)
    last_error = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    synced_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
