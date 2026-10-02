"""Retry one private training recording upload to its batch Drive folder."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: F401
from app.database import SessionLocal
from app.models.ai import AILectureRecording
from app.native_ai.recording_worker import upload_training_recording


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording-id", type=int, required=True)
    args = parser.parse_args()
    with SessionLocal() as db:
        recording = db.get(AILectureRecording, args.recording_id)
        if not recording or recording.deleted_at is not None:
            print("Upload refused: recording not found", file=sys.stderr)
            return 1
        result = upload_training_recording(db, recording)
    print(json.dumps({"recording_id": args.recording_id, **result}))
    return 0 if result["status"] == "uploaded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
