"""Private recording preparation queue for an institution-operated worker."""
from datetime import datetime, timezone
import subprocess

from sqlalchemy.orm import Session

from app.config import settings
from app.core.recording_storage import prepared_media_path, recording_root
from app.models.ai import (AIAuditLog, AILectureContent, AILecturePreparationJob,
                           AILectureRecording)
from app.native_ai.lecture_digest import build_digest
from app.native_ai.model_runtime import model_capabilities, run_slide_ocr, run_speech_model
from app.native_ai.recording_media import prepare_recording_media, verify_recording_file


def _safe_error_code(error: Exception) -> str:
    message = str(error).lower()
    if "ffmpeg" in message and ("not installed" in message or "unavailable" in message):
        return "ffmpeg_unavailable"
    if "hash changed" in message or "size has changed" in message or "recording is missing" in message:
        return "recording_integrity_failed"
    if "already exists" in message:
        return "prepared_media_exists"
    if "no usable audio" in message or "no usable" in message:
        return "required_media_stream_missing"
    if isinstance(error, subprocess.TimeoutExpired):
        return "preparation_timeout"
    safe_model_codes = {
        "speech_model_unavailable", "speech_model_execution_failed",
        "speech_model_invalid_segments", "speech_model_transcript_length_invalid",
        "slide_ocr_model_unavailable", "slide_ocr_execution_failed",
        "slide_ocr_invalid_output", "model_output_missing_or_too_large",
        "model_output_invalid_json", "model_output_schema_unsupported",
        "model_output_invalid_text", "model_output_combined_text_too_large",
    }
    if str(error) in safe_model_codes:
        return str(error)
    return "media_preparation_failed"


def process_next_recording_job(db: Session, institution_id: int | None = None,
                               ffmpeg_binary: str = "ffmpeg", frame_interval_seconds: int = 30,
                               runner=subprocess.run) -> dict | None:
    query = db.query(AILecturePreparationJob).filter(AILecturePreparationJob.status == "queued")
    if institution_id is not None:
        query = query.filter(AILecturePreparationJob.institution_id == institution_id)
    query = query.order_by(AILecturePreparationJob.requested_at, AILecturePreparationJob.id)
    if db.bind and db.bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    job = query.first()
    if not job:
        return None
    recording = db.query(AILectureRecording).filter(
        AILectureRecording.id == job.recording_id,
        AILectureRecording.institution_id == job.institution_id,
        AILectureRecording.deleted_at.is_(None)).first()
    if not recording:
        job.status = "cancelled"
        job.stage = "recording_unavailable"
        job.error_code = "recording_unavailable"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        return {"job_id": job.id, "status": job.status, "error_code": job.error_code}
    job.status = "processing"
    job.stage = "verifying_recording"
    job.attempts += 1
    job.started_at = datetime.now(timezone.utc)
    job.finished_at = None
    job.error_code = None
    recording.status = "preparing_media"
    db.commit()
    try:
        prepared_path = prepared_media_path(recording_root(), recording.storage_key)
        audio_path = prepared_path / "audio.wav"
        frames_path = prepared_path / "frames"
        if audio_path.is_file() and frames_path.is_dir():
            verify_recording_file(recording)
            result = {"audio_prepared": True,
                      "sampled_frame_count": len(list(frames_path.glob("*.jpg")))}
            recording.status = "media_prepared"
            db.commit()
        else:
            result = prepare_recording_media(db, recording.id, recording.institution_id,
                                             ffmpeg_binary, frame_interval_seconds, runner)
        capabilities = model_capabilities(settings.native_speech_model_executable,
            settings.native_speech_model_id, settings.native_slide_ocr_executable,
            settings.native_slide_ocr_model_id)
        notes_created = False
        slides = None
        if capabilities["speech_model_available"]:
            timeout = settings.native_model_timeout_minutes * 60
            speech = run_speech_model(audio_path, settings.native_speech_model_executable,
                                      settings.native_speech_model_id, timeout, runner)
            slides = run_slide_ocr(frames_path, settings.native_slide_ocr_executable,
                                   settings.native_slide_ocr_model_id, timeout, runner)
            transcript = speech["transcript"]
            if slides and slides["slides"]:
                transcript += "\n" + "\n".join(
                    f"[Slide {row['timestamp_ms'] // 60000:02d}:{(row['timestamp_ms'] // 1000) % 60:02d}] {row['text']}"
                    for row in slides["slides"])
            if len(transcript) > 100000:
                raise RuntimeError("model_output_combined_text_too_large")
            existing = db.query(AILectureContent).filter(
                AILectureContent.session_id == recording.session_id,
                AILectureContent.institution_id == recording.institution_id).first()
            if not existing:
                summary = build_digest(transcript)
                summary["model_provenance"] = {
                    "speech_model_id": speech["model_id"],
                    "segment_count": speech["segment_count"],
                    "average_confidence": speech["average_confidence"],
                    "language": speech["language"],
                    "slide_ocr_model_id": slides["model_id"] if slides else None,
                    "slide_count": slides["slide_count"] if slides else 0,
                    "recording_id": recording.id,
                }
                existing = AILectureContent(institution_id=recording.institution_id,
                    course_id=recording.course_id, session_id=recording.session_id,
                    submitted_by=job.requested_by, transcript=transcript,
                    transcript_source="ekeekrta_local_models", summary=summary, status="draft")
                db.add(existing)
                db.add(AIAuditLog(institution_id=recording.institution_id,
                    user_id=job.requested_by, event_type="lecture_model_draft_prepared",
                    details={"recording_id": recording.id, "course_id": recording.course_id,
                             "session_id": recording.session_id,
                             "speech_model_id": speech["model_id"],
                             "slide_ocr_used": bool(slides)}))
                notes_created = True
            recording.status = "transcript_draft_ready"
            db.flush()
        job = db.get(AILecturePreparationJob, job.id)
        job.status = "completed"
        job.stage = ("transcript_draft_ready_for_faculty_review" if notes_created
                     else "existing_lecture_preserved" if capabilities["speech_model_available"]
                     else "media_prepared_awaiting_transcription_model")
        job.result = {"audio_prepared": result["audio_prepared"],
                      "sampled_frame_count": result["sampled_frame_count"],
                      "transcript_created": notes_created if capabilities["speech_model_available"] else False,
                      "notes_created": notes_created if capabilities["speech_model_available"] else False,
                      "slide_ocr_used": bool(slides) if capabilities["speech_model_available"] else False}
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        return {"job_id": job.id, "status": job.status, "stage": job.stage,
                "result": job.result}
    except Exception as error:
        db.rollback()
        job = db.get(AILecturePreparationJob, job.id)
        recording = db.get(AILectureRecording, recording.id)
        job.status = "failed"
        job.stage = "media_preparation_failed"
        job.error_code = _safe_error_code(error)
        job.finished_at = datetime.now(timezone.utc)
        if recording and recording.deleted_at is None:
            prepared_path = prepared_media_path(recording_root(), recording.storage_key)
            recording.status = ("media_prepared" if (prepared_path / "audio.wav").is_file()
                                else "preparation_failed")
        db.commit()
        return {"job_id": job.id, "status": job.status, "stage": job.stage,
                "error_code": job.error_code}
