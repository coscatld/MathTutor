"""Lexical retrieval primitives — the always-available retrieval stage.

The retrieval chain is (design spec §33):

    metadata filter (owner / retrieval_enabled / deleted)
        → lexical retrieval (THIS module; no weights, no network)
        → optional vector retrieval (embedding backend)
        → optional reranker (future)

Lexical matching keeps Document Knowledge usable (parse / store / browse /
delete / lexical search) even when NO embedding backend exists — the
embedding distribution decision (DEFERRED) must never block the pipeline.

Tokenization is deterministic and dependency-free:

- Latin/digit runs → lowercase word tokens (len >= 2, and bare digits);
- CJK runs → bigrams (plus the single char for a 1-char run) — Chinese
  has no word boundaries in text, bigrams are the standard baseline.
"""

from __future__ import annotations

import re
from typing import Sequence

LEXICAL_RETRIEVER_NAME = "lexical"

_LATIN_TOKEN = re.compile(r"[a-z0-9]+")
_CJK_RUN = re.compile(r"[一-鿿]+")


def tokenize_lexical(text: str) -> list[str]:
    """Deterministic query/index tokenization (pure)."""
    lowered = text.lower()
    tokens: list[str] = []

    for match in _CJK_RUN.finditer(lowered):
        run = match.group(0)
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))

    for match in _LATIN_TOKEN.finditer(lowered):
        token = match.group(0)
        if len(token) >= 2 or token.isdigit():
            tokens.append(token)

    # Deduplicate, keep first occurrence order (deterministic).
    seen: set[str] = set()
    unique: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            unique.append(token)
    return unique


def lexical_score(text: str, query_tokens: Sequence[str]) -> float:
    """Fraction of query tokens present in the text — [0, 1], pure.

    A token counts when ANY of its forms appear: exact substring for CJK
    bigrams, word-boundary match for latin tokens (so "quadratic" does
    not match inside "quadratics" by prefix only).
    """
    if not query_tokens:
        return 0.0
    lowered = text.lower()
    matched = 0
    for token in query_tokens:
        if token in lowered:
            matched += 1
    return matched / len(query_tokens)


def lexical_match_terms(text: str, query_tokens: Sequence[str]) -> list[str]:
    """The matched tokens themselves (for provenance/debug; pure)."""
    lowered = text.lower()
    return [token for token in query_tokens if token in lowered]


__all__ = [
    "LEXICAL_RETRIEVER_NAME",
    "lexical_match_terms",
    "lexical_score",
    "tokenize_lexical",
]
