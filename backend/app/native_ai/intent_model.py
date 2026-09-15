import math
import re
from collections import Counter, defaultdict


TRAINING_PHRASES = {
    "schedule_class": [
        "schedule a class", "plan a meeting", "schedule lecture tomorrow", "create class meeting",
        "arrange a class at ten", "book an online class", "set up course meeting",
        "schedule course on date at time", "schedule machine learning at ten",
    ],
    "draft_assignment": [
        "create assignment", "draft an assignment", "prepare homework", "make coursework",
        "assignment on this topic", "set an assignment for the course",
    ],
    "draft_quiz": [
        "create quiz", "draft a quiz", "prepare multiple choice questions", "make a test",
        "quiz on this topic", "build weekly test questions",
    ],
    "student_progress": [
        "show my progress", "student performance", "check attendance and marks", "who is at risk",
        "show learner progress", "analyse academic performance", "give progress insight",
    ],
    "import_erp_students": [
        "import students from erp", "sync student accounts", "get learners from erp",
        "bring student profiles from college erp", "synchronise erp students",
        "import users from erp", "import users based on role", "sync faculty and hod from erp",
    ],
    "create_department": [
        "create department", "add a department", "set up academic department",
        "make a new department", "register institution department",
    ],
    "create_course": [
        "create course", "add a course", "set up academic course", "make a new subject",
        "create non academic course", "register course for a semester",
    ],
    "bulk_create_accounts": [
        "create accounts in bulk", "bulk import students", "bulk create faculty",
        "upload account csv", "import accounts from csv", "register many students",
    ],
    "help": [
        "what can you do", "help me", "show commands", "how does this work", "available actions",
    ],
}


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]


class NativeIntentModel:
    """Small multinomial Naive Bayes classifier trained from EKEEKRTA-owned phrases."""

    def __init__(self, phrases=None):
        self.phrases = phrases or TRAINING_PHRASES
        self.counts = defaultdict(Counter)
        self.totals = Counter()
        self.documents = Counter()
        self.vocabulary = set()
        for intent, examples in self.phrases.items():
            for example in examples:
                tokens = _tokens(example)
                self.counts[intent].update(tokens)
                self.totals[intent] += len(tokens)
                self.documents[intent] += 1
                self.vocabulary.update(tokens)
        self.document_count = sum(self.documents.values())

    def predict(self, text: str) -> tuple[str, float]:
        # Unknown names, course codes and dates are handled by slot extraction;
        # they must not dilute the intent score.
        tokens = [token for token in _tokens(text) if token in self.vocabulary]
        if not tokens:
            return "help", 0.0
        vocab_size = max(1, len(self.vocabulary))
        scores = {}
        for intent in self.phrases:
            score = math.log(self.documents[intent] / self.document_count)
            denominator = self.totals[intent] + vocab_size
            for token in tokens:
                score += math.log((self.counts[intent][token] + 1) / denominator)
            scores[intent] = score
        best = max(scores, key=scores.get)
        peak = max(scores.values())
        probabilities = {key: math.exp(value - peak) for key, value in scores.items()}
        confidence = probabilities[best] / sum(probabilities.values())
        return best, round(confidence, 4)


model = NativeIntentModel()
