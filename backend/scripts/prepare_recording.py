"""Operator-only local media preparation for a completed class recording.

Run from backend/. No raw media, database credentials, or FFmpeg diagnostics
are printed. A trained institution-owned speech/vision model is still required.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
import app.models  # noqa: F401 - register every table before queries
from app.native_ai.recording_media import prepare_recording_media


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording-id", type=int, required=True)
    parser.add_argument("--institution-id", type=int, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg", help="FFmpeg executable path or PATH command")
    parser.add_argument("--frame-interval-seconds", type=int, default=30)
    args = parser.parse_args()
    with SessionLocal() as db:
        try:
            result = prepare_recording_media(db, args.recording_id, args.institution_id,
                                             args.ffmpeg, args.frame_interval_seconds)
        except (ValueError, RuntimeError) as error:
            print(f"Preparation refused: {error}", file=sys.stderr)
            return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
