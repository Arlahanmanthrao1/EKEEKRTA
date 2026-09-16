"""Process queued Stage 4 media preparation jobs on a private institution machine."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
import app.models  # noqa: F401 - register all tables
from app.native_ai.recording_worker import process_next_recording_job


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institution-id", type=int)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--frame-interval-seconds", type=int, default=30)
    parser.add_argument("--max-jobs", type=int, default=1, choices=range(1, 101), metavar="1-100")
    args = parser.parse_args()
    completed = 0
    with SessionLocal() as db:
        while completed < args.max_jobs:
            result = process_next_recording_job(db, args.institution_id, args.ffmpeg,
                                                args.frame_interval_seconds)
            if result is None:
                break
            print(json.dumps(result))
            completed += 1
    if completed == 0:
        print(json.dumps({"status": "idle", "processed_jobs": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
