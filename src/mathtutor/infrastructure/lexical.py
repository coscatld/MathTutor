"""Lexical retrieval primitives — the always-available retrieval stage.

The retrieval chain is (design spec §33):

    metadata filter (owner / retrieval_enabled / deleted)
        → lexical retrieval (THIS module + FTS5 over pre-tokenized fts_text)
        → optional vector retrieval (embedding backend; NEVER required)
        → optional reranker (future)

Lexical matching keeps Document Knowledge usable even when NO embedding
backend exists — the embedding distribution decision (DEFERRED) must
never block the pipeline.

Tokenization is deterministic and dependency-free:

- Latin/digit runs → lowercase word tokens (len >= 2, and bare digits);
- CJK runs → bigrams (plus the single char for a 1-char run) AND the
  full run so a knowledge-point title is one FTS token;
- LaTeX dollar-delimiters stripped so ``2x+3=7`` matches ``$2x+3=7$``.
"""

from __future__ import annotations

import math
import re
from typing import Sequence

LEXICAL_RETRIEVER_NAME = "lexical"

_LATIN_TOKEN = re.compile(r"[a-z0-9]+")
_CJK_RUN = re.compile(r"[一-鿿]+")
_DOLLAR_DELIM = re.compile(r"\$+")
_LATEX_WRAP = re.compile(r"\\[\[\]()]")
_SIMPLE_FORMULA = re.compile(r"[0-9a-zA-Z]+(?:\s*[+\-*/=]\s*[0-9a-zA-Z]+)+")
_EXAMPLE_NO = re.compile(r"例\s*题?\s*([0-9０-９]+|[一二三四五六七八九十]{1,3})")


def normalize_latex_plain(text: str) -> str:
    """Drop ``$`` / ``\\( \\)`` wrappers; keep the inner math as plain text."""
    stripped = _DOLLAR_DELIM.sub(" ", text or "")
    stripped = _LATEX_WRAP.sub(" ", stripped)
    return " ".join(stripped.split())


def compact_formulas(text: str) -> list[str]:
    """Space-free copies of simple equations (``2x + 3 = 7`` → ``2x+3=7``)."""
    found: list[str] = []
    for match in _SIMPLE_FORMULA.finditer(text or ""):
        compact = re.sub(r"\s+", "", match.group(0))
        if compact:
            found.append(compact.lower())
    return found


def build_fts_text(
    text: str,
    *,
    heading_path: Sequence[str] = (),
    section: str = "",
    metadata: dict | None = None,
) -> str:
    """Pre-tokenized index string stored on the chunk and in FTS5.

    Space-separated so unicode61 can split. Includes: latex-plain copy,
    CJK bigrams + full runs, latin tokens, compact formulas, example
    numbers, heading path, and skill/concept aliases.
    """
    meta = metadata or {}
    latex_bits = []
    raw_latex = meta.get("latex")
    if isinstance(raw_latex, str) and raw_latex.strip():
        latex_bits.append(raw_latex)
    heading = [str(part) for part in heading_path if part]
    if section:
        heading.append(section)
    blob = "\n".join([text or "", *heading, *latex_bits])
    plain = normalize_latex_plain(blob)
    tokens: list[str] = []
    tokens.append(plain)
    tokens.extend(tokenize_lexical(plain))
    for run in _CJK_RUN.findall(plain):
        tokens.append(run)
    tokens.extend(compact_formulas(plain))
    for match in _EXAMPLE_NO.finditer(plain):
        number = re.sub(r"\s+", "", match.group(0))
        tokens.append(number)
        tokens.append(f"例{match.group(1)}")
    from mathtutor.application.retrieval_query import aliases_for_blob

    tokens.extend(aliases_for_blob(plain, *heading))
    return " ".join(_unique_keep_order(tokens))


def fts_query_tokens(query: str) -> list[str]:
    """Tokens used for FTS5 MATCH (bigrams + full CJK runs + compact formulas)."""
    plain = normalize_latex_plain(query or "")
    tokens = list(tokenize_lexical(plain))
    for run in _CJK_RUN.findall(plain):
        if run not in tokens:
            tokens.append(run)
    for formula in compact_formulas(plain):
        if formula not in tokens:
            tokens.append(formula)
    for match in _EXAMPLE_NO.finditer(plain):
        token = f"例{match.group(1)}"
        if token not in tokens:
            tokens.append(token)
    return tokens


def fts_match_query(tokens: Sequence[str]) -> str:
    """OR-query of double-quoted tokens (FTS5 unicode61)."""
    parts: list[str] = []
    for token in tokens:
        stripped = (token or "").strip()
        if not stripped:
            continue
        parts.append('"' + stripped.replace('"', '""') + '"')
    return " OR ".join(parts)


def fts_rank_component(bm25_value: float) -> float:
    """Map FTS5 bm25 (more negative = better) to (0, 1]."""
    return 1.0 / (1.0 + math.exp(float(bm25_value)))


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

    return _unique_keep_order(tokens)


def _unique_keep_order(tokens: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for token in tokens:
        if token and token not in seen:
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
    "build_fts_text",
    "compact_formulas",
    "fts_match_query",
    "fts_query_tokens",
    "fts_rank_component",
    "lexical_match_terms",
    "lexical_score",
    "normalize_latex_plain",
    "tokenize_lexical",
]
