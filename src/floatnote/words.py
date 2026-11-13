"""Word fixes: learn "always write X when you hear Y" from the user's edits."""

import difflib
import re

MAX_PHRASE_WORDS = 3


def _words(text: str) -> list[str]:
    return re.findall(r"[\w'.-]+", text)


def suggest_fix(before: str, after: str, known: dict[str, str] | None = None) -> tuple[str, str] | None:
    """If an edit replaced a short phrase, return (heard, correct) to offer as a fix.

    "the whitetail admin" -> "the Wagtail admin" gives ("whitetail", "Wagtail").
    Pure rewrites, additions and deletions give None.
    """
    known = known or {}
    a, b = _words(before), _words(after)
    matcher = difflib.SequenceMatcher(a=[w.lower() for w in a], b=[w.lower() for w in b], autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal" and any(x != y for x, y in zip(a[i1:i2], b[j1:j2])):
            op = "case"  # same words, different capitals (api -> API)
        if op not in ("replace", "case"):
            continue
        heard, right = " ".join(a[i1:i2]), " ".join(b[j1:j2])
        if op == "case":  # only offer the first word whose case changed
            pair = next((x, y) for x, y in zip(a[i1:i2], b[j1:j2]) if x != y)
            heard, right = pair
        if not (1 <= len(heard.split()) <= MAX_PHRASE_WORDS and 1 <= len(right.split()) <= MAX_PHRASE_WORDS):
            continue
        if known.get(heard.lower()) == right:
            continue
        return heard.lower(), right
    return None
