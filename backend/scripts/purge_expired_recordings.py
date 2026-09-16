"""Preview or apply the explicitly configured private-recording retention policy."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
import app.models  # noqa: F401
from app.native_ai.recording_retention import purge_expired_recordings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-delete", action="store_true",
                        help="Permanently remove eligible raw and derived media")
    args = parser.parse_args()
    with SessionLocal() as db:
        try:
            result = purge_expired_recordings(db, args.confirm_delete)
        except (ValueError, RuntimeError) as error:
            print(f"Retention refused: {error}", file=sys.stderr); return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
