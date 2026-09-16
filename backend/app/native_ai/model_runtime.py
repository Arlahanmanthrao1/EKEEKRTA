"""Strict, offline contract for institution-built speech and slide models.

No executable is downloaded and no network fallback exists. Model processes
receive private local paths and must write bounded JSON to a temporary path.
"""
import json
from pathlib import Path
import re
import subprocess
import uuid


def _executable_path(configured: str) -> Path | None:
    if not configured.strip():
        return None
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    path = path.resolve()
    return path if path.is_file() else None


def model_capabilities(speech_executable: str, speech_model_id: str,
                       ocr_executable: str, ocr_model_id: str) -> dict:
    return {
        "speech_model_available": bool(_executable_path(speech_executable) and speech_model_id.strip()),
        "slide_ocr_available": bool(_executable_path(ocr_executable) and ocr_model_id.strip()),
    }


def _read_output(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size == 0 or path.stat().st_size > 5 * 1024 * 1024:
        raise RuntimeError("model_output_missing_or_too_large")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RuntimeError("model_output_invalid_json") from None
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise RuntimeError("model_output_schema_unsupported")
    return payload


def _clean_text(value, maximum=2000) -> str:
    if not isinstance(value, str):
        raise RuntimeError("model_output_invalid_text")
    text = re.sub(r"\s+", " ", value).strip()
    if not text or len(text) > maximum:
        raise RuntimeError("model_output_invalid_text")
    return text


def _timestamp(milliseconds: int) -> str:
    seconds = milliseconds // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def run_speech_model(audio_path: Path, executable: str, model_id: str,
                     timeout_seconds: int, runner=subprocess.run) -> dict:
    binary = _executable_path(executable)
    if not binary or not model_id.strip():
        raise RuntimeError("speech_model_unavailable")
    output = audio_path.parent / f".speech-{uuid.uuid4().hex}.json"
    try:
        runner([str(binary), "--input-audio", str(audio_path), "--output-json", str(output)],
               check=True, timeout=timeout_seconds, stdout=subprocess.DEVNULL,
               stderr=subprocess.DEVNULL, shell=False)
        payload = _read_output(output)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise RuntimeError("speech_model_execution_failed") from None
    finally:
        output.unlink(missing_ok=True)
    segments = payload.get("segments")
    if not isinstance(segments, list) or not 1 <= len(segments) <= 5000:
        raise RuntimeError("speech_model_invalid_segments")
    lines, previous_start, confidences = [], -1, []
    for segment in segments:
        if not isinstance(segment, dict):
            raise RuntimeError("speech_model_invalid_segments")
        start, end = segment.get("start_ms"), segment.get("end_ms")
        confidence = segment.get("confidence")
        if (not isinstance(start, int) or not isinstance(end, int) or start < previous_start
                or start < 0 or end <= start or not isinstance(confidence, (int, float))
                or not 0 <= confidence <= 1):
            raise RuntimeError("speech_model_invalid_segments")
        speaker = _clean_text(segment.get("speaker", "Speaker"), 80)
        text = _clean_text(segment.get("text"))
        lines.append(f"[{_timestamp(start)}] {speaker}: {text}")
        confidences.append(float(confidence)); previous_start = start
    transcript = "\n".join(lines)
    if len(transcript) < 180 or len(transcript) > 100000:
        raise RuntimeError("speech_model_transcript_length_invalid")
    return {"transcript": transcript, "segment_count": len(lines),
            "average_confidence": round(sum(confidences) / len(confidences), 4),
            "language": _clean_text(payload.get("language", "unknown"), 40),
            "model_id": model_id.strip()}


def run_slide_ocr(frames_path: Path, executable: str, model_id: str,
                  timeout_seconds: int, runner=subprocess.run) -> dict | None:
    if not executable.strip() and not model_id.strip():
        return None
    binary = _executable_path(executable)
    if not binary or not model_id.strip():
        raise RuntimeError("slide_ocr_model_unavailable")
    output = frames_path.parent / f".slides-{uuid.uuid4().hex}.json"
    try:
        runner([str(binary), "--input-frames", str(frames_path), "--output-json", str(output)],
               check=True, timeout=timeout_seconds, stdout=subprocess.DEVNULL,
               stderr=subprocess.DEVNULL, shell=False)
        payload = _read_output(output)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise RuntimeError("slide_ocr_execution_failed") from None
    finally:
        output.unlink(missing_ok=True)
    slides = payload.get("slides")
    if not isinstance(slides, list) or len(slides) > 500:
        raise RuntimeError("slide_ocr_invalid_output")
    cleaned = []
    for slide in slides:
        if (not isinstance(slide, dict) or not isinstance(slide.get("timestamp_ms"), int)
                or isinstance(slide.get("timestamp_ms"), bool) or slide["timestamp_ms"] < 0):
            raise RuntimeError("slide_ocr_invalid_output")
        confidence = slide.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise RuntimeError("slide_ocr_invalid_output")
        cleaned.append({"timestamp_ms": slide["timestamp_ms"], "text": _clean_text(slide.get("text")),
                        "confidence": float(confidence)})
    return {"slides": cleaned, "slide_count": len(cleaned), "model_id": model_id.strip()}
