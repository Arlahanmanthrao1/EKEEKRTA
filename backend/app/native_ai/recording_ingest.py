"""Trusted host-side import of a finalized Jibri recording."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import uuid

from sqlalchemy.orm import Session

from app.config import settings
from app.core.recording_storage import recording_path, recording_root
from app.models.ai import AIAuditLog, AILecturePreparationJob, AILectureRecording
from app.models.attendance import ClassSession
from app.models.course import Course
from app.models.user import User, UserRole


def ingest_jibri_recording(db: Session, session_id: int, source: Path,
                           permissions_confirmed: bool) -> AILectureRecording:
    if not permissions_confirmed:
        raise ValueError("recording_permission_not_confirmed")
    session = db.get(ClassSession, session_id)
    if not session or session.ended_at is None:
        raise ValueError("completed_class_session_not_found")
    course = db.get(Course, session.course_id)
    if not course:
        raise ValueError("recording_course_not_found")
    uploader = db.get(User, course.faculty_id) if course.faculty_id else None
    if not uploader:
        uploader = db.query(User).filter(User.institution_id == course.institution_id,
                                         User.role == UserRole.admin).order_by(User.id).first()
    if not uploader:
        raise ValueError("recording_owner_not_found")
    source = source.resolve()
    suffix = source.suffix.lower()
    if not source.is_file() or suffix not in (".mp4", ".webm"):
        raise ValueError("jibri_recording_file_invalid")
    maximum = settings.jibri_recording_max_mb * 1024 * 1024
    if source.stat().st_size <= 0 or source.stat().st_size > maximum:
        raise ValueError("jibri_recording_size_invalid")
    with source.open("rb") as input_file:
        header = input_file.read(64 * 1024)
    if not ((suffix == ".mp4" and len(header) >= 12 and header[4:8] == b"ftyp")
            or (suffix == ".webm" and header.startswith(b"\x1a\x45\xdf\xa3"))):
        raise ValueError("jibri_recording_header_invalid")
    existing = db.query(AILectureRecording).filter(
        AILectureRecording.institution_id == course.institution_id,
        AILectureRecording.session_id == session.id,
        AILectureRecording.deleted_at.is_(None)).first()
    if existing:
        return existing
    root = recording_root(); root.mkdir(parents=True, exist_ok=True)
    storage_key = f"{uuid.uuid4().hex}{suffix}"
    target = recording_path(root, storage_key)
    digest, size = hashlib.sha256(), 0
    try:
        with source.open("rb") as input_file, target.open("xb") as output_file:
            for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                size += len(chunk); digest.update(chunk); output_file.write(chunk)
        item = AILectureRecording(institution_id=course.institution_id, course_id=course.id,
            session_id=session.id, uploaded_by=uploader.id, original_filename=source.name[:180],
            content_type="video/mp4" if suffix == ".mp4" else "video/webm",
            storage_key=storage_key, size_bytes=size, sha256=digest.hexdigest(),
            status="preparation_queued")
        db.add(item); db.flush()
        db.add(AILecturePreparationJob(institution_id=course.institution_id,
            course_id=course.id, recording_id=item.id, requested_by=uploader.id,
            status="queued", stage="awaiting_private_worker"))
        db.add(AIAuditLog(institution_id=course.institution_id, user_id=uploader.id,
            event_type="jibri_recording_imported",
            details={"recording_id": item.id, "course_id": course.id,
                     "session_id": session.id, "size_bytes": size}))
        db.commit(); db.refresh(item)
        return item
    except Exception:
        db.rollback(); target.unlink(missing_ok=True); raise
