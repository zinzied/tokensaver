"""Heuristic task-difficulty classifier (zero-dependency, stdlib only).

Scores a task description on a 0-100 scale and buckets it into
EASY / MEDIUM / HARD. Routing intent:

- HARD   tasks  -> strong (paid) model, so quality is never lost
- EASY   tasks  -> free model, saving money and tokens
- MEDIUM tasks  -> free but capable code/tool model
"""

import re

HARD_STRONG = [
    "architecture", "architect", "distributed", "concurrency", "deadlock",
    "race condition", "security", "vulnerability", "encryption", "microservice",
    "microservices", "scalability", "scaling", "optimize", "optimization",
    "refactor", "refactoring", "migrate", "migration", "algorithm", "production",
    "deployment", "protocol", "websocket", "kubernetes", "k8s", "sharding",
    "redesign", "rewrite", "performance",
]

HARD_MODERATE = [
    "debug", "debugging", "bug", "auth", "oauth", "jwt", "database", "sql",
    "docker", "test", "testing", "review", "merge", "conflict", "regex", "cache",
    "thread", "threading", "async", "network", "api", "complex", "complicated",
    "design", "legacy", "upgrade", "dependency", "pipeline", "ci/cd", "terraform",
    "monitoring", "logging", "error handling", "exception", "indexing", "query",
    "schema", "optimization", "scaling", "distributed", "monolith",
]

EASY = [
    "typo", "rename", "rename variable", "format", "formatting", "comment",
    "docstring", "spelling", "hello", "hello world", "simple", "basic", "quick",
    "trivial", "minor", "greeting", "fix typo", "explain", "what is", "copy",
    "paste", "add comment", "small change",
]

EASY_BOUND = 35
HARD_BOUND = 65

# Phrases that suggest a worker is out of its depth -> escalation signal.
UNCERTAIN_PHRASES = [
    "i'm not sure", "i am not sure", "i'm unsure", "i am unsure", "not certain",
    "uncertain", "i don't know", "i do not know", "cannot determine", "can't determine",
    "unable to", "not enough information", "insufficient information", "ambiguous",
    "i'm not confident", "i am not confident", "may be wrong", "i can't say",
]


def is_uncertain(text):
    """True when a response signals the worker was out of its depth (escalation trigger)."""
    low = (text or "").lower()
    return any(p in low for p in UNCERTAIN_PHRASES)


def classify(text):
    """Return {'label': EASY|MEDIUM|HARD, 'score': int 0-100}."""
    text = (text or "").lower()
    score = 30
    for w in HARD_STRONG:
        if w in text:
            score += 12
    for w in HARD_MODERATE:
        if w in text:
            score += 6
    for w in EASY:
        if w in text:
            score -= 8
    words = len(re.findall(r"[a-z0-9]+", text))
    if words > 400:
        score += 12
    elif words > 200:
        score += 6
    score = max(0, min(100, score))
    if score >= HARD_BOUND:
        label = "HARD"
    elif score >= EASY_BOUND:
        label = "MEDIUM"
    else:
        label = "EASY"
    return {"label": label, "score": score}
