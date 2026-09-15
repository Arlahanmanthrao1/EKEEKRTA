"""Small, explainable lexical retriever for approved EKEEKRTA course text.

This is deliberately extractive: it returns passages from approved sources and
does not invent prose when the evidence is weak. It uses no external service or
pretrained model.
"""
import math
import re
from collections import Counter


STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "define", "do", "does", "explain",
    "for", "from", "how", "i", "in", "is", "it", "me", "of", "on", "or", "please", "tell", "that",
    "the", "their", "this", "to", "what", "when", "where", "which", "who", "why", "with",
}


def _tokens(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9][a-z0-9_-]+", value.lower()) if token not in STOP_WORDS]


def _chunks(content: str) -> list[str]:
    clean = re.sub(r"[ \t]+", " ", content.replace("\r", "\n"))
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", clean) if part.strip()]
    result = []
    for paragraph in paragraphs or [clean.strip()]:
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", paragraph) if part.strip()]
        if not sentences:
            continue
        for index in range(0, len(sentences), 2):
            result.append(" ".join(sentences[index:index + 2])[:900])
    return result


def retrieve(question: str, sources, limit: int = 3) -> dict:
    query = _tokens(question)
    if not query:
        return {"answered": False, "answer": "Ask a specific question using course topic terms.", "citations": []}

    records = []
    for source in sources:
        for passage in _chunks(source.content):
            tokens = _tokens(passage)
            if tokens:
                records.append((source, passage, tokens))
    if not records:
        return {"answered": False, "answer": "No approved course content is available yet.", "citations": []}

    document_frequency = Counter()
    for _, _, tokens in records:
        document_frequency.update(set(tokens))
    total = len(records)
    query_phrase = " ".join(query)
    ranked = []
    for source, passage, tokens in records:
        counts = Counter(tokens)
        overlap = set(query) & set(tokens)
        if not overlap:
            continue
        score = sum((1 + math.log(counts[token])) * (math.log((total + 1) / (document_frequency[token] + .5)) + 1)
                    for token in overlap)
        coverage = len(overlap) / len(set(query))
        score *= .65 + coverage
        if len(query) > 1 and query_phrase in " ".join(tokens):
            score += 3
        ranked.append((score, source, passage, coverage))
    ranked.sort(key=lambda item: (-item[0], item[1].id))

    best = ranked[:limit]
    # One weak match to one broad token is not enough evidence for a confident answer.
    if not best or (len(set(query)) >= 2 and best[0][3] < .34):
        return {
            "answered": False,
            "answer": "I could not find enough evidence in the approved course sources. Ask the faculty member to add relevant material or rephrase with the course topic.",
            "citations": [],
        }
    citations = [{"source_id": source.id, "title": source.title, "source_type": source.source_type,
                  "excerpt": passage, "relevance": round(score, 2)}
                 for score, source, passage, _ in best]
    return {
        "answered": True,
        "answer": "The approved course sources contain the following relevant information:",
        "citations": citations,
    }
