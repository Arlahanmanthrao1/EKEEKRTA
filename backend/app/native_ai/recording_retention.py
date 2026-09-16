"""Explicit private-recording retention policy; notes are preserved."""
from datetime import datetime, timedelta, timezone
import shutil

from sqlalchemy.orm import Session

from app.config import settings
from app.core.recording_storage import prepared_media_path, recording_path, recording_root
from app.models.ai import AIAuditLog, AILecturePreparationJob, AILectureRecording


def purge_expired_recordings(db: Session, confirm_delete: bool = False) -> dict:
    days = settings.recording_retention_days
    if days <= 0:
        raise ValueError("recording_retention_policy_disabled")
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.query(AILectureRecording).filter(
        AILectureRecording.deleted_at.is_(None),
        AILectureRecording.created_at < cutoff).order_by(AILectureRecording.id).all()
    candidates = []
    for item in rows:
        active = db.query(AILecturePreparationJob.id).filter(
            AILecturePreparationJob.recording_id == item.id,
            AILecturePreparationJob.status.in_(("queued", "processing"))).first()
        if not active:
            candidates.append(item)
    if not confirm_delete:
        return {"retention_days": days, "eligible_recording_ids": [row.id for row in candidates],
                "deleted": 0, "dry_run": True}
    root = recording_root()
    now = datetime.now(timezone.utc)
    for item in candidates:
        raw = recording_path(root, item.storage_key)
        prepared = prepared_media_path(root, item.storage_key)
        if prepared.exists():
            shutil.rmtree(prepared)
        raw.unlink(missing_ok=True)
        item.status = "expired"
        item.deleted_at = now
        db.add(AIAuditLog(institution_id=item.institution_id, user_id=item.uploaded_by,
            event_type="lecture_recording_expired",
            details={"recording_id": item.id, "course_id": item.course_id,
                     "session_id": item.session_id, "retention_days": days}))
    db.commit()
    return {"retention_days": days, "eligible_recording_ids": [row.id for row in candidates],
            "deleted": len(candidates), "dry_run": False}
