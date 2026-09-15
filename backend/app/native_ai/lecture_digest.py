"""Extractive lecture digest: selected transcript statements, never invented claims."""
import re
from collections import Counter

from app.native_ai.course_retrieval import STOP_WORDS


def build_digest(transcript: str) -> dict:
    clean = re.sub(r"[ \t]+", " ", transcript.replace("\r", "\n")).strip()
    statements = [part.strip(" -•\t") for part in re.split(r"(?<=[.!?])\s+|\n+", clean)
                  if len(part.strip()) >= 30]
    if len(statements) < 3:
        raise ValueError("Add at least three complete lecture statements before creating notes")
    words = [word.lower() for statement in statements
             for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", statement)
             if word.lower() not in STOP_WORDS]
    frequencies = Counter(words)
    topics = [word for word, count in frequencies.most_common(12) if count >= 2][:8]
    ranked = sorted(enumerate(statements), key=lambda row: (
        -sum(frequencies[word.lower()] for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", row[1])
             if word.lower() not in STOP_WORDS) / max(len(row[1].split()), 1), row[0]))
    chosen = sorted(ranked[:min(6, len(statements))], key=lambda row: row[0])
    highlights = [{"statement_number": index + 1, "text": statement} for index, statement in chosen]
    return {"summary": " ".join(item["text"] for item in highlights),
            "notes": highlights, "candidate_notes": highlights,
            "topics": topics, "candidate_topics": topics, "statement_count": len(statements),
            "method": "extractive_transcript_selection", "external_model": False,
            "review_required": True}
