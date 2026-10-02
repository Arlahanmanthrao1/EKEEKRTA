"""Validate private EKEEKRTA voice data without copying or printing transcripts."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import sys
import wave


REQUIRED = {"sample_id", "audio_path", "transcript", "language", "speaker_id", "role",
            "device", "noise_condition", "consent_id", "recorded_at", "split"}
ROLES = {"student", "faculty", "hod", "admin"}
SPLITS = {"train", "validation", "test"}
NON_SPEECH_CONDITIONS = {"silence", "background_noise", "unknown_speech"}


def _inside(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError("audio_path escapes the private dataset directory") from None
    return candidate


def validate(root: Path, manifest: Path) -> tuple[dict, list[str]]:
    root = root.resolve()
    errors, seen_ids = [], set()
    counts, seconds = Counter(), Counter()
    speakers_by_split = defaultdict(set)
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            return {}, [f"Manifest is missing columns: {', '.join(sorted(missing))}"]
        for line, row in enumerate(reader, start=2):
            prefix = f"Row {line}"
            sample_id = (row["sample_id"] or "").strip()
            if not sample_id or sample_id in seen_ids:
                errors.append(f"{prefix}: sample_id is empty or duplicated")
            seen_ids.add(sample_id)
            role, split = row["role"].strip().lower(), row["split"].strip().lower()
            if role not in ROLES:
                errors.append(f"{prefix}: unsupported role")
            if split not in SPLITS:
                errors.append(f"{prefix}: split must be train, validation or test")
                continue
            transcript = " ".join((row["transcript"] or "").split())
            noise_condition = row["noise_condition"].strip().lower()
            if not transcript and noise_condition not in NON_SPEECH_CONDITIONS:
                errors.append(f"{prefix}: transcript length is invalid")
            elif len(transcript) > 2000:
                errors.append(f"{prefix}: transcript length is invalid")
            if not row["consent_id"].strip():
                errors.append(f"{prefix}: consent_id is required")
            try:
                datetime.fromisoformat(row["recorded_at"].strip().replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{prefix}: recorded_at is not an ISO date/time")
            speaker = row["speaker_id"].strip()
            if not speaker:
                errors.append(f"{prefix}: speaker_id is required")
            speakers_by_split[split].add(speaker)
            try:
                audio = _inside(root, row["audio_path"].strip())
                if audio.suffix.lower() != ".wav" or not audio.is_file():
                    raise ValueError("audio is not an existing WAV file")
                with wave.open(str(audio), "rb") as source:
                    if source.getnchannels() != 1 or source.getframerate() != 16000 or source.getsampwidth() != 2:
                        raise ValueError("WAV must be mono, 16 kHz and signed 16-bit PCM")
                    duration = source.getnframes() / source.getframerate()
                    if not 0.5 <= duration <= 20:
                        raise ValueError("duration must be between 0.5 and 20 seconds")
            except (OSError, EOFError, wave.Error, ValueError) as exc:
                errors.append(f"{prefix}: {exc}")
                continue
            counts[split] += 1
            seconds[split] += duration
    for first in SPLITS:
        for second in SPLITS:
            if first < second:
                overlap = speakers_by_split[first] & speakers_by_split[second]
                if overlap:
                    errors.append(f"Speaker leakage between {first} and {second}: {len(overlap)} speaker(s)")
    summary = {"samples": sum(counts.values()),
               "hours": round(sum(seconds.values()) / 3600, 2),
               "splits": {split: {"samples": counts[split], "hours": round(seconds[split] / 3600, 2),
                                  "speakers": len(speakers_by_split[split])} for split in sorted(SPLITS)}}
    return summary, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate private EKEEKRTA voice recordings and manifest")
    parser.add_argument("--dataset", required=True, type=Path, help="Private dataset root")
    parser.add_argument("--manifest", type=Path, help="CSV manifest; defaults to <dataset>/manifest.csv")
    arguments = parser.parse_args()
    root = arguments.dataset.resolve()
    manifest = (arguments.manifest or root / "manifest.csv").resolve()
    if not root.is_dir() or not manifest.is_file():
        print("Dataset directory or manifest.csv was not found.", file=sys.stderr)
        return 2
    summary, errors = validate(root, manifest)
    print(f"Validated samples: {summary.get('samples', 0)}")
    print(f"Validated duration: {summary.get('hours', 0)} hours")
    for split, values in summary.get("splits", {}).items():
        print(f"{split}: {values['samples']} samples, {values['hours']} hours, {values['speakers']} speakers")
    if errors:
        print(f"Validation failed with {len(errors)} issue(s):", file=sys.stderr)
        for error in errors[:100]:
            print(f"- {error}", file=sys.stderr)
        if len(errors) > 100:
            print("- Additional issues omitted.", file=sys.stderr)
        return 1
    print("Dataset structure passed validation. This does not certify model quality or consent compliance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
