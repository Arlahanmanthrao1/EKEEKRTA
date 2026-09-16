"""Import one finalized Jibri directory and queue private Stage 4 processing."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.database import SessionLocal
import app.models  # noqa: F401
from app.native_ai.recording_ingest import ingest_jibri_recording


def _find_session_id(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "ekeekrta_session_id" and str(child).isdigit():
                return int(child)
            found = _find_session_id(child)
            if found is not None:
                return found
    if isinstance(value, list):
        for child in value:
            found = _find_session_id(child)
            if found is not None:
                return found
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording-directory", required=True)
    parser.add_argument("--session-id", type=int)
    parser.add_argument("--permissions-confirmed", action="store_true", required=True)
    args = parser.parse_args()
    if not settings.jibri_recordings_dir:
        print("Import refused: JIBRI_RECORDINGS_DIR is not configured", file=sys.stderr); return 1
    allowed = Path(settings.jibri_recordings_dir).expanduser().resolve()
    directory = Path(args.recording_directory).expanduser().resolve()
    if not directory.is_dir() or directory == allowed or allowed not in directory.parents:
        print("Import refused: recording directory is outside JIBRI_RECORDINGS_DIR", file=sys.stderr); return 1
    recordings = [path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in (".mp4", ".webm")]
    if len(recordings) != 1:
        print("Import refused: expected exactly one MP4 or WebM in the finalized directory", file=sys.stderr); return 1
    session_id = args.session_id
    if session_id is None:
        for metadata in directory.rglob("*.json"):
            try:
                session_id = _find_session_id(json.loads(metadata.read_text(encoding="utf-8")))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if session_id is not None:
                break
    if session_id is None:
        print("Import refused: no ekeekrta_session_id was found; pass --session-id", file=sys.stderr); return 1
    with SessionLocal() as db:
        try:
            item = ingest_jibri_recording(db, session_id, recordings[0], args.permissions_confirmed)
        except (ValueError, RuntimeError) as error:
            print(f"Import refused: {error}", file=sys.stderr); return 1
    print(json.dumps({"recording_id": item.id, "session_id": item.session_id,
                      "status": item.status, "processing_queued": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
