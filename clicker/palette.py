"""Fuzzy matching for the command palette: type a few letters, get the best commands first."""

import re

_WORD = re.compile(r"[a-z0-9]+")


def _word_score(w, text, starts):
    """How well one typed word matches text (lowercase); None when it doesn't."""
    i = text.find(w)
    if i >= 0:
        if i in starts:
            return 100.0 - min(i, 40) * 0.5           # starts a word: "rec" in "Start recording"
        return 60.0 - min(i, 40) * 0.3                 # inside a word
    # letters in order, favouring word starts and runs: "nsc" -> "New script"
    pos, total, prev = 0, 0.0, -2
    for ch in w:
        j = text.find(ch, pos)
        if j < 0:
            return None
        total += 6 if j in starts else (4 if j == prev + 1 else 1)
        prev, pos = j, j + 1
    return total


def score(query, text):
    """Higher is better; None when text doesn't match every word of query."""
    words = query.lower().split()
    if not words:
        return 0.0
    t = text.lower()
    starts = {m.start() for m in _WORD.finditer(t)}
    total = 0.0
    for w in words:
        s = _word_score(w, t, starts)
        if s is None:
            return None
        total += s
    return total - len(t) * 0.05   # among equals, the shorter (more exact) title wins


def rank(query, items, limit=60):
    """items: dicts with 'title' and optionally 'keywords' and 'boost'. Best first; stable for ties."""
    scored = []
    for n, it in enumerate(items):
        s = score(query, it["title"])
        k = score(query, it.get("keywords", "")) if it.get("keywords") else None
        if k is not None:
            k -= 15  # matching only a hidden keyword counts a little less than the title
            s = k if s is None else max(s, k)
        if s is not None:
            scored.append((-(s + it.get("boost", 0)), n, it))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [it for _s, _n, it in scored[:limit]]
