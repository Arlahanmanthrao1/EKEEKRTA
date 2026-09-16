"""Completed-class transcript review and private local recording intake."""
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import shutil
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.core.access import course_access, tenant
from app.core.recording_storage import prepared_media_path, recording_path, recording_root
from app.core.deps import get_current_user
from app.database import get_db
from app.models.ai import (AIAuditLog, AIKnowledgeSource, AILectureContent,
                           AILecturePreparationJob, AILectureRecording)
from app.models.attendance import ClassSession
from app.models.user import User, UserRole
from app.native_ai.lecture_digest import build_digest
from app.native_ai.model_runtime import model_capabilities
from app.schemas.lecture import (LectureContentOut, LecturePublicationIn, LectureReviewIn,
                                 LectureTranscriptIn, LectureRecordingOut,
                                 LectureRecordingCapabilitiesOut,
                                 LectureRecordingPreparationOut)

router = APIRouter(prefix="/ai/lectures", tags=["native-ai-lectures"])


def _lecture_out(item: AILectureContent, manager: bool) -> LectureContentOut:
    summary = dict(item.summary)
    if not manager:
        summary.pop("candidate_notes", None)
        summary.pop("candidate_topics", None)
        summary.pop("reviewed_by", None)
        summary.pop("model_provenance", None)
    return LectureContentOut(id=item.id, course_id=item.course_id, session_id=item.session_id,
                             status=item.status, transcript_source=item.transcript_source,
                             summary=summary, transcript=item.transcript if manager else None,
                             created_at=item.created_at, updated_at=item.updated_at)


def _manager(db: Session, user: User, course_id: int):
    if user.role not in (UserRole.faculty, UserRole.admin):
        raise HTTPException(403, "Only course faculty or administrators can review lecture transcripts")
    return course_access(db, user, course_id, manage=True)


def _audit(db: Session, user: User, event: str, item: AILectureContent):
    db.add(AIAuditLog(institution_id=tenant(user), user_id=user.id, event_type=event,
                      details={"lecture_id": item.id, "course_id": item.course_id,
                               "session_id": item.session_id, "status": item.status}))


def _recording_root() -> Path:
    try:
        return recording_root()
    except ValueError:
        raise HTTPException(500, "Choose a dedicated private recording directory")


def _preparation_out(item: AILecturePreparationJob) -> LectureRecordingPreparationOut:
    return LectureRecordingPreparationOut(id=item.id, recording_id=item.recording_id,
        status=item.status, stage=item.stage, attempts=item.attempts,
        error_code=item.error_code, requested_at=item.requested_at,
        started_at=item.started_at, finished_at=item.finished_at)


def _recording_out(item: AILectureRecording, notes_status: str | None,
                   preparation: AILecturePreparationJob | None = None) -> LectureRecordingOut:
    return LectureRecordingOut(id=item.id, course_id=item.course_id, session_id=item.session_id,
                               original_filename=item.original_filename, content_type=item.content_type,
                               size_bytes=item.size_bytes, status=item.status, notes_status=notes_status,
                               preparation=_preparation_out(preparation) if preparation else None,
                               created_at=item.created_at)


def _recording_audit(db: Session, user: User, event: str, item: AILectureRecording):
    db.add(AIAuditLog(institution_id=tenant(user), user_id=user.id, event_type=event,
                      details={"recording_id": item.id, "course_id": item.course_id,
                               "session_id": item.session_id, "size_bytes": item.size_bytes}))


@router.get("/recording-capabilities", response_model=LectureRecordingCapabilitiesOut)
def recording_capabilities(user: User = Depends(get_current_user)):
    if user.role not in (UserRole.faculty, UserRole.admin):
        raise HTTPException(403, "Only faculty or administrators can manage recordings")
    local = not bool(os.getenv("VERCEL"))
    models = model_capabilities(settings.native_speech_model_executable,
        settings.native_speech_model_id, settings.native_slide_ocr_executable,
        settings.native_slide_ocr_model_id)
    return LectureRecordingCapabilitiesOut(local_upload_available=local,
        preparation_queue_available=local, maximum_upload_mb=settings.recording_max_upload_mb,
        automatic_recording_available=(local and settings.video_provider == "jitsi"
                                       and settings.jitsi_auto_recording_enabled),
        automatic_transcription_available=local and models["speech_model_available"],
        slide_ocr_available=local and models["slide_ocr_available"])


@router.get("/recordings/course/{course_id}", response_model=list[LectureRecordingOut])
def list_recordings(course_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _manager(db, user, course_id)
    recordings = db.query(AILectureRecording).filter(
        AILectureRecording.institution_id == tenant(user),
        AILectureRecording.course_id == course_id,
        AILectureRecording.deleted_at.is_(None)).order_by(AILectureRecording.id.desc()).limit(100).all()
    lecture_status = {row.session_id: row.status for row in db.query(AILectureContent).filter(
        AILectureContent.institution_id == tenant(user), AILectureContent.course_id == course_id).all()}
    jobs = {row.recording_id: row for row in db.query(AILecturePreparationJob).filter(
        AILecturePreparationJob.institution_id == tenant(user),
        AILecturePreparationJob.course_id == course_id).all()}
    return [_recording_out(item, lecture_status.get(item.session_id), jobs.get(item.id)) for item in recordings]


@router.post("/recordings/{recording_id}/prepare", response_model=LectureRecordingPreparationOut)
def queue_recording_preparation(recording_id: int, db: Session = Depends(get_db),
                                user: User = Depends(get_current_user)):
    if os.getenv("VERCEL"):
        raise HTTPException(503, "Recording preparation requires a private institution worker")
    item = db.query(AILectureRecording).filter(AILectureRecording.id == recording_id,
        AILectureRecording.institution_id == tenant(user), AILectureRecording.deleted_at.is_(None)).first()
    if not item:
        raise HTTPException(404, "Recording not found")
    _manager(db, user, item.course_id)
    models = model_capabilities(settings.native_speech_model_executable,
        settings.native_speech_model_id, settings.native_slide_ocr_executable,
        settings.native_slide_ocr_model_id)
    has_lecture = db.query(AILectureContent.id).filter(
        AILectureContent.session_id == item.session_id,
        AILectureContent.institution_id == tenant(user)).first()
    if item.status in ("media_prepared", "transcript_draft_ready") and (
            not models["speech_model_available"] or has_lecture):
        detail = ("A private transcript draft already exists" if has_lecture
                  else "Private audio and frames are prepared; configure the EKEEKRTA speech model to continue")
        raise HTTPException(409, detail)
    job = db.query(AILecturePreparationJob).filter(
        AILecturePreparationJob.recording_id == item.id,
        AILecturePreparationJob.institution_id == tenant(user)).first()
    if job and job.status in ("queued", "processing"):
        return _preparation_out(job)
    now = datetime.now(timezone.utc)
    if job:
        job.requested_by = user.id
        job.status = "queued"
        job.stage = "awaiting_private_worker"
        job.result = None
        job.error_code = None
        job.requested_at = now
        job.started_at = None
        job.finished_at = None
    else:
        job = AILecturePreparationJob(institution_id=tenant(user), course_id=item.course_id,
            recording_id=item.id, requested_by=user.id, status="queued",
            stage="awaiting_private_worker")
        db.add(job)
    item.status = "preparation_queued"
    db.flush()
    _recording_audit(db, user, "lecture_recording_preparation_queued", item)
    try:
        db.commit(); db.refresh(job)
    except IntegrityError:
        db.rollback()
        concurrent = db.query(AILecturePreparationJob).filter(
            AILecturePreparationJob.recording_id == item.id).first()
        if concurrent:
            return _preparation_out(concurrent)
        raise HTTPException(409, "Recording preparation was queued concurrently") from None
    return _preparation_out(job)


@router.post("/sessions/{session_id}/recording", response_model=LectureRecordingOut, status_code=201)
def upload_recording(session_id: int, file: UploadFile = File(...),
                     permissions_confirmed: bool = Form(...), db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    if os.getenv("VERCEL"):
        raise HTTPException(503, "Recording uploads require a private institution recording worker; Vercel does not store media")
    if not permissions_confirmed:
        raise HTTPException(422, "Confirm participants were informed and recording processing is permitted")
    session = db.get(ClassSession, session_id)
    if not session:
        raise HTTPException(404, "Class session not found")
    course = _manager(db, user, session.course_id)
    if session.ended_at is None:
        raise HTTPException(409, "End the class before uploading its recording")
    existing = db.query(AILectureRecording).filter(AILectureRecording.session_id == session_id,
                                                    AILectureRecording.institution_id == tenant(user)).first()
    if existing and existing.deleted_at is None:
        raise HTTPException(409, "A recording is already stored for this class; remove it before replacing")
    filename = Path((file.filename or "recording").replace("\\", "/")).name[:180]
    suffix = Path(filename).suffix.lower()
    content_type = (file.content_type or "").lower()
    if suffix not in (".mp4", ".webm") or content_type not in ("video/mp4", "video/webm", "application/octet-stream"):
        raise HTTPException(422, "Upload an MP4 or WebM meeting recording")
    root = _recording_root()
    root.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        root.chmod(0o700)
    storage_key = f"{uuid.uuid4().hex}{suffix}"
    target = recording_path(root, storage_key)
    maximum = settings.recording_max_upload_mb * 1024 * 1024
    size = 0
    digest = hashlib.sha256()
    committed = False
    try:
        with target.open("xb") as output:
            first = file.file.read(64 * 1024)
            valid_mp4 = suffix == ".mp4" and len(first) >= 12 and first[4:8] == b"ftyp"
            valid_webm = suffix == ".webm" and first.startswith(b"\x1a\x45\xdf\xa3")
            if not (valid_mp4 or valid_webm):
                raise HTTPException(422, "This file does not have an MP4 or WebM header")
            chunk = first
            while chunk:
                size += len(chunk)
                if size > maximum:
                    raise HTTPException(413, f"Recording exceeds the {settings.recording_max_upload_mb} MB local limit")
                digest.update(chunk)
                output.write(chunk)
                chunk = file.file.read(64 * 1024)
        if os.name != "nt":
            target.chmod(0o600)
        if existing:
            existing.uploaded_by = user.id
            existing.original_filename = filename
            existing.content_type = content_type
            existing.storage_key = storage_key
            existing.size_bytes = size
            existing.sha256 = digest.hexdigest()
            existing.status = "uploaded"
            existing.created_at = datetime.now(timezone.utc)
            existing.deleted_at = None
            item = existing
        else:
            item = AILectureRecording(institution_id=tenant(user), course_id=course.id,
                                      session_id=session.id, uploaded_by=user.id,
                                      original_filename=filename, content_type=content_type,
                                      storage_key=storage_key, size_bytes=size,
                                      sha256=digest.hexdigest(), status="uploaded")
            db.add(item)
        db.flush()
        _recording_audit(db, user, "lecture_recording_uploaded", item)
        db.commit(); committed = True; db.refresh(item)
        lecture = db.query(AILectureContent).filter(AILectureContent.session_id == session_id,
                                                   AILectureContent.institution_id == tenant(user)).first()
        return _recording_out(item, lecture.status if lecture else None)
    except IntegrityError:
        if not committed:
            db.rollback()
            target.unlink(missing_ok=True)
        raise HTTPException(409, "A recording was uploaded concurrently for this class") from None
    except Exception:
        if not committed:
            db.rollback()
            target.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()


@router.delete("/recordings/{recording_id}", status_code=204)
def remove_recording(recording_id: int, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    if os.getenv("VERCEL"):
        raise HTTPException(503, "Recording deletion requires the private institution recording worker")
    item = db.query(AILectureRecording).filter(AILectureRecording.id == recording_id,
        AILectureRecording.institution_id == tenant(user), AILectureRecording.deleted_at.is_(None)).first()
    if not item:
        raise HTTPException(404, "Recording not found")
    _manager(db, user, item.course_id)
    root = _recording_root()
    try:
        target = recording_path(root, item.storage_key)
        prepared = prepared_media_path(root, item.storage_key)
    except ValueError:
        raise HTTPException(500, "Invalid private recording path")
    if prepared.exists():
        shutil.rmtree(prepared)
    target.unlink(missing_ok=True)
    job = db.query(AILecturePreparationJob).filter(
        AILecturePreparationJob.recording_id == item.id).first()
    if job and job.status in ("queued", "processing"):
        job.status = "cancelled"
        job.stage = "recording_removed"
        job.finished_at = datetime.now(timezone.utc)
    item.status = "deleted"
    item.deleted_at = datetime.now(timezone.utc)
    _recording_audit(db, user, "lecture_recording_deleted", item)
    db.commit()


@router.post("/sessions/{session_id}/transcript", response_model=LectureContentOut, status_code=201)
def submit_transcript(session_id: int, payload: LectureTranscriptIn, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    session = db.get(ClassSession, session_id)
    if not session:
        raise HTTPException(404, "Class session not found")
    course = _manager(db, user, session.course_id)
    if session.ended_at is None:
        raise HTTPException(409, "End the class before preparing lecture notes")
    if re.search(r"\b(password|private key|api[_ -]?token|secret key)\b", payload.transcript, re.I):
        raise HTTPException(422, "Remove passwords, private keys and API tokens from the transcript")
    try:
        digest = build_digest(payload.transcript)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    item = db.query(AILectureContent).filter(AILectureContent.session_id == session_id,
                                             AILectureContent.institution_id == tenant(user)).first()
    if item and item.status == "published":
        raise HTTPException(409, "Unpublish the current lecture notes before replacing the transcript")
    if item:
        provenance = item.summary.get("model_provenance") if isinstance(item.summary, dict) else None
        item.transcript = payload.transcript
        if item.transcript_source == "ekeekrta_local_models" or provenance:
            item.transcript_source = "faculty_corrected_local_model"
            digest["model_provenance"] = {**(provenance or {}), "corrected_by_faculty": True}
        item.summary = digest
        item.status = "draft"
    else:
        item = AILectureContent(institution_id=tenant(user), course_id=course.id,
                                session_id=session.id, submitted_by=user.id,
                                transcript=payload.transcript, transcript_source="faculty_text",
                                summary=digest, status="draft")
        db.add(item)
    db.flush()
    _audit(db, user, "lecture_transcript_digest_prepared", item)
    db.commit(); db.refresh(item)
    return _lecture_out(item, True)


@router.get("/course/{course_id}", response_model=list[LectureContentOut])
def list_lectures(course_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    course = course_access(db, user, course_id)
    manager = user.role == UserRole.admin or (user.role == UserRole.faculty and course.faculty_id == user.id)
    query = db.query(AILectureContent).filter(AILectureContent.institution_id == tenant(user),
                                               AILectureContent.course_id == course_id)
    if not manager:
        query = query.filter(AILectureContent.status == "published")
    return [_lecture_out(item, manager) for item in query.order_by(AILectureContent.id.desc()).limit(100).all()]


@router.patch("/{lecture_id}/review", response_model=LectureContentOut)
def review_lecture(lecture_id: int, payload: LectureReviewIn,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.query(AILectureContent).filter(AILectureContent.id == lecture_id,
                                              AILectureContent.institution_id == tenant(user)).first()
    if not item:
        raise HTTPException(404, "Lecture notes not found")
    _manager(db, user, item.course_id)
    if item.status == "published":
        raise HTTPException(409, "Unpublish the lecture notes before changing the review")
    candidate_notes = item.summary.get("candidate_notes") or item.summary.get("notes") or []
    candidate_topics = item.summary.get("candidate_topics") or item.summary.get("topics") or []
    allowed = {note["statement_number"] for note in candidate_notes}
    requested = payload.included_statement_numbers
    if len(set(requested)) != len(requested) or not set(requested) <= allowed:
        raise HTTPException(422, "Select distinct statements from this transcript draft")
    if len(set(payload.included_topics)) != len(payload.included_topics) or not set(payload.included_topics) <= set(candidate_topics):
        raise HTTPException(422, "Select distinct topics from this transcript draft")
    notes = [note for note in candidate_notes if note["statement_number"] in requested]
    summary = dict(item.summary)
    summary.update({"notes": notes, "topics": [topic for topic in candidate_topics if topic in payload.included_topics],
                    "summary": " ".join(note["text"] for note in notes),
                    "candidate_notes": candidate_notes, "candidate_topics": candidate_topics,
                    "review_required": False, "reviewed_by": user.id})
    item.summary = summary
    item.status = "reviewed"
    _audit(db, user, "lecture_digest_reviewed", item)
    db.commit(); db.refresh(item)
    return _lecture_out(item, True)


@router.patch("/{lecture_id}/publication", response_model=LectureContentOut)
def change_publication(lecture_id: int, payload: LecturePublicationIn,
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.query(AILectureContent).filter(AILectureContent.id == lecture_id,
                                              AILectureContent.institution_id == tenant(user)).first()
    if not item:
        raise HTTPException(404, "Lecture notes not found")
    _manager(db, user, item.course_id)
    if payload.publish:
        if item.status not in ("reviewed", "published") or item.summary.get("review_required", True):
            raise HTTPException(409, "Review and select transcript statements before publishing")
        if not item.summary.get("notes"):
            raise HTTPException(409, "This transcript has no reviewable notes")
        if item.knowledge_source_id:
            source = db.query(AIKnowledgeSource).filter(AIKnowledgeSource.id == item.knowledge_source_id,
                                                       AIKnowledgeSource.institution_id == tenant(user)).first()
        else:
            source = None
        if source is None:
            source = AIKnowledgeSource(institution_id=tenant(user), course_id=item.course_id,
                                       created_by=user.id, title=f"Lecture {item.session_id} reviewed notes",
                                       source_type="lecture", content="\n".join(
                                           row["text"] for row in item.summary["notes"]), is_published=True)
            db.add(source); db.flush()
            item.knowledge_source_id = source.id
        else:
            source.content = "\n".join(row["text"] for row in item.summary["notes"])
            source.is_published = True
            source.archived_at = None
        item.status = "published"
    else:
        item.status = "reviewed" if not item.summary.get("review_required", True) else "draft"
        if item.knowledge_source_id:
            source = db.query(AIKnowledgeSource).filter(AIKnowledgeSource.id == item.knowledge_source_id,
                                                       AIKnowledgeSource.institution_id == tenant(user)).first()
            if source:
                source.is_published = False
    _audit(db, user, "lecture_digest_published" if payload.publish else "lecture_digest_unpublished", item)
    db.commit(); db.refresh(item)
    return _lecture_out(item, True)
