from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func

from app.database import Base


class GoogleDriveConnection(Base):
    __tablename__ = "google_drive_connections"
    __table_args__ = (UniqueConstraint("user_id", name="uq_google_drive_user"),)

    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    google_email = Column(String(254), nullable=False)
    encrypted_refresh_token = Column(Text, nullable=False)
    scopes = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    revoked_at = Column(DateTime(timezone=True), nullable=True)


class GoogleDriveOAuthState(Base):
    __tablename__ = "google_drive_oauth_states"

    id = Column(Integer, primary_key=True)
    institution_id = Column(Integer, ForeignKey("institutions.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    state_hash = Column(String(64), nullable=False, unique=True, index=True)
    encrypted_code_verifier = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
