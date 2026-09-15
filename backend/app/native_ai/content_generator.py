"""Deterministic, source-grounded teaching drafts owned by EKEEKRTA.

The generator never calls an external model. It extracts facts and terms from
faculty-provided notes, then produces reviewable assignment and quiz drafts.
"""
import re
from collections import Counter


class ContentDraftError(ValueError):
    pass


STOP_WORDS = {
    "about", "after", "again", "also", "among", "because", "before", "being", "between", "could",
    "does", "each", "from", "have", "into", "more", "most", "other", "should", "such", "than",
    "that", "their", "these", "they", "this", "through", "using", "very", "what", "when", "where",
    "which", "while", "with", "would", "your", "there", "then", "were", "will", "been", "only",
}


def _clean_source(source: str) -> str:
    return re.sub(r"[\t ]+", " ", source.replace("\r", "\n")).strip()


def _sentences(source: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", _clean_source(source))
    return [re.sub(r"^[\s\-•*\d.)]+", "", part).strip() for part in parts if len(part.strip()) >= 24][:80]


def _valid_term(value: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z0-9-]*", value)
    return bool(words) and len(words) <= 5 and not all(word.lower() in STOP_WORDS for word in words)


def _terms(sentences: list[str]) -> list[str]:
    candidates: list[str] = []
    for sentence in sentences:
        definition = re.match(r"(?:The\s+)?(.{2,70}?)\s+(?:is|are|means|refers to|describes)\s+", sentence, re.I)
        if definition and _valid_term(definition.group(1)):
            candidates.append(definition.group(1).strip(" ,:;-"))
        candidates.extend(match.group(0) for match in re.finditer(r"\b(?:[A-Z][A-Za-z0-9-]*)(?:\s+[A-Z][A-Za-z0-9-]*){0,3}\b", sentence))

    words = [word for sentence in sentences for word in re.findall(r"\b[A-Za-z][A-Za-z0-9-]{4,}\b", sentence)]
    counts = Counter(word.lower() for word in words if word.lower() not in STOP_WORDS)
    spelling = {}
    for word in words:
        spelling.setdefault(word.lower(), word)
    candidates.extend(spelling[word] for word, _ in counts.most_common(30))

    unique = []
    seen = set()
    for candidate in candidates:
        normalized = re.sub(r"\s+", " ", candidate).strip(" ,:;.-").casefold()
        if len(normalized) < 3 or normalized in seen or not _valid_term(candidate):
            continue
        seen.add(normalized)
        unique.append(re.sub(r"\s+", " ", candidate).strip(" ,:;.-"))
    return unique[:40]


def _source_profile(source: str) -> tuple[list[str], list[str]]:
    sentences = _sentences(source)
    if len(sentences) < 2:
        raise ContentDraftError("Add at least two complete lesson-note statements before generating a draft")
    terms = _terms(sentences)
    if len(terms) < 4:
        raise ContentDraftError("Add at least four distinct subject terms or definitions to the lesson notes")
    return sentences, terms


def build_assignment_draft(topic: str, source: str) -> dict:
    sentences, terms = _source_profile(source)
    focus = terms[:4]
    description = (
        f"Topic: {topic}\n\n"
        "Learning goals\n"
        + "\n".join(f"- Explain {term} using the supplied lesson notes." for term in focus[:3])
        + "\n\nFaculty-reviewed task\n"
        f"1. Explain the core ideas of {topic} in your own words.\n"
        f"2. Show how {focus[0]} relates to {focus[1]} using an example or worked application.\n"
        f"3. Compare the roles of {focus[2]} and {focus[3]}.\n"
        "4. Cite the relevant statements from the provided course material.\n\n"
        "Submission guidance: Use the course submission link and follow any additional instructions added by the faculty."
    )
    return {
        "title": f"{topic} assignment"[:160],
        "description": description,
        "focus_terms": focus,
        "source_highlights": sentences[:3],
        "source_sentence_count": len(sentences),
    }


def build_quiz_draft(topic: str, source: str, requested_count: int) -> dict:
    sentences, terms = _source_profile(source)
    questions = []
    used_answers = set()
    for sentence in sentences:
        matching = [term for term in terms if term.casefold() not in used_answers and
                    re.search(rf"\b{re.escape(term)}\b", sentence, re.I)]
        if not matching:
            continue
        answer = max(matching, key=len)
        distractors = [term for term in terms if term.casefold() != answer.casefold() and
                       not re.search(rf"\b{re.escape(term)}\b", sentence, re.I)]
        if len(distractors) < 3:
            continue
        prompt = re.sub(rf"\b{re.escape(answer)}\b", "_____", sentence, count=1, flags=re.I)
        correct_index = len(questions) % 4
        options = distractors[:3]
        options.insert(correct_index, answer)
        questions.append({"text": f"Which option correctly completes this statement from the lesson notes? {prompt}",
                          "options": options, "correct_option": correct_index,
                          "correct_answer": answer,
                          "source_statement": sentence})
        used_answers.add(answer.casefold())
        if len(questions) >= requested_count:
            break
    if not questions:
        raise ContentDraftError("The notes do not contain enough distinct facts to create a source-grounded quiz")
    return {
        "title": f"{topic} quiz"[:160],
        "questions": questions,
        "requested_question_count": requested_count,
        "generated_question_count": len(questions),
        "source_sentence_count": len(sentences),
        "warning": None if len(questions) == requested_count else
                   f"Only {len(questions)} source-grounded question(s) could be created from these notes.",
    }
