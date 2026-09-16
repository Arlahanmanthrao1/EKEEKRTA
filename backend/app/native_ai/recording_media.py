"""Prepare private audio and sampled video frames for a future local AI model.

This module never transcribes speech, reads slide text, or publishes notes.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import mkdtemp

from sqlalchemy.orm import Session

from app.core.recording_storage import prepared_media_path, recording_path, recording_root
from app.models.ai import AILectureRecording


def verify_recording_file(item: AILectureRecording) -> Path:
    root = recording_root()
    source = recording_path(root, item.storage_key)
    if not source.is_file() or source.stat().st_size != item.size_bytes:
        raise RuntimeError("Private recording is missing or its size has changed")
    digest = hashlib.sha256()
    with source.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != item.sha256:
        raise RuntimeError("Private recording hash changed; preparation refused")
    return source


def prepare_recording_media(db: Session, recording_id: int, institution_id: int,
                            ffmpeg_binary: str = "ffmpeg", frame_interval_seconds: int = 30,
                            runner=subprocess.run) -> dict:
    if os.getenv("VERCEL"):
        raise RuntimeError("Media preparation must run on a private institution worker")
    if frame_interval_seconds < 5 or frame_interval_seconds > 120:
        raise ValueError("Frame interval must be between 5 and 120 seconds")
    item = db.query(AILectureRecording).filter(
        AILectureRecording.id == recording_id,
        AILectureRecording.institution_id == institution_id,
        AILectureRecording.deleted_at.is_(None)).first()
    if not item:
        raise ValueError("Private recording not found for this institution")
    binary = shutil.which(ffmpeg_binary)
    if not binary:
        raise RuntimeError("FFmpeg is not installed or the supplied executable is unavailable")
    root = recording_root()
    source = verify_recording_file(item)
    target = prepared_media_path(root, item.storage_key)
    if target.exists():
        raise ValueError("Prepared media already exists; do not overwrite it")
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        target.parent.chmod(0o700)
    temporary_path = Path(mkdtemp(prefix="prep-", dir=target.parent))
    try:
        frames = temporary_path / "frames"
        frames.mkdir()
        audio = temporary_path / "audio.wav"
        common = [binary, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(source)]
        runner(common + ["-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
                         "-c:a", "pcm_s16le", str(audio)], check=True, timeout=3600,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        runner(common + ["-map", "0:v:0", "-an", "-vf", f"fps=1/{frame_interval_seconds}",
                         "-frames:v", "500", "-q:v", "3", str(frames / "%06d.jpg")],
               check=True, timeout=3600, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        frame_count = len(list(frames.glob("*.jpg")))
        if not audio.is_file() or audio.stat().st_size == 0 or frame_count == 0:
            raise RuntimeError("FFmpeg produced no usable audio or screen frames")
        temporary_path.rename(target)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise RuntimeError("FFmpeg could not prepare this recording; private diagnostics were suppressed") from None
    finally:
        if temporary_path.exists() and temporary_path.parent.resolve() == target.parent:
            shutil.rmtree(temporary_path)
    item.status = "media_prepared"
    try:
        db.commit()
    except Exception:
        db.rollback()
        # Only this validated, newly created derivative directory is removed.
        shutil.rmtree(target)
        raise
    return {"recording_id": recording_id, "status": "media_prepared", "audio_prepared": True,
            "sampled_frame_count": frame_count, "transcript_created": False,
            "notes_created": False}
