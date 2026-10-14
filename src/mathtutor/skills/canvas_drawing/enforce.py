"""Remove every figure the model drew by itself from model-authored text.

The only figures a student sees are scenes the application built from a
``draw_scene`` call. Everything else that tries to be a picture is replaced by
``FIGURE_NOTE``: forged ``mathtutor-scene``/``mathtutor-graph`` blocks,
Markdown images, HTML ``img``/``svg``/``canvas``, drawing code blocks
(Mermaid, TikZ, SVG, plotting code, text art), LaTeX picture environments and
ASCII-art blocks. Ordinary maths, Markdown tables and LaTeX are kept.
"""

from __future__ import annotations

import re

FIGURE_NOTE = "（图示请用画布查看）"

_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})[ \t]*([^\n`~]*)\n(.*?)(?:^[ \t]*\1[ \t]*$|\Z)", re.M | re.S)
_DRAW_LANGS = re.compile(
    r"^(?:mathtutor-scene|mathtutor-graph|mermaid|tikz|svg|html|xml|plantuml|puml|graphviz|dot|ditaa|"
    r"ascii|ascii-?art|art|text-?art|diagram|chart|plot|figure|asymptote|asy|metapost|pgfplots|geogebra|desmos)\b", re.I)
_DRAW_CODE = re.compile(
    r"matplotlib|pyplot|\bplt\.|plotly|seaborn|bokeh|turtle|\bggplot|getContext\s*\(|<svg|<canvas|\bd3\.|new\s+Chart\s*\(|"
    r"Chart\.js|echarts|\\begin\{(?:tikzpicture|picture|pspicture|axis)\}|graph\s+(?:TD|LR|TB|RL|BT)\b|flowchart\s|"
    r"sequenceDiagram|@startuml|digraph\s", re.I)
_PLAIN_LANGS = re.compile(r"^(?:|text|txt|plain|plaintext|none|console)$", re.I)
_MARKDOWN_IMAGE = re.compile(r"!\[[^\]\n]*\]\([^)\n]*\)|!\[[^\]\n]*\]\[[^\]\n]*\]")
_HTML_FIGURE = re.compile(
    r"<svg\b.*?(?:</svg\s*>|\Z)|<canvas\b.*?(?:</canvas\s*>|/>|\Z)|<img\b[^>]*>|<picture\b.*?(?:</picture\s*>|\Z)|"
    r"<iframe\b.*?(?:</iframe\s*>|/>|\Z)", re.I | re.S)
_LATEX_PICTURE = re.compile(
    r"\\begin\{(tikzpicture|picture|pspicture|tikzcd|axis)\}.*?(?:\\end\{\1\}|\Z)", re.S)
_TOKEN = re.compile(r"mathtutor-(?:scene|graph)", re.I)

_ART = set("|/\\_-+*─│┌┐└┘├┤┬┴┼╱╲·•○●━┃═║╔╗╚╝╭╮╰╯▲▼◀▶△▽→←↑↓")
_PROSE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


def _drawing_fence(language: str, body: str) -> bool:
    language = language.strip().split()[0] if language.strip() else ""
    if _DRAW_LANGS.match(language) or _DRAW_CODE.search(body):
        return True
    return bool(_PLAIN_LANGS.match(language)) and _art_runs(body.split("\n"), minimum=2)


def _art_line(line: str) -> bool:
    chars = [c for c in line if not c.isspace()]
    if not chars:
        return False
    art = sum(c in _ART for c in chars)
    prose = len(_PROSE.findall(line))
    cjk = len(re.findall(r"[\u4e00-\u9fff]", line))
    return art >= 1 and art >= 0.6 * len(chars) and prose <= 3 and cjk <= 1


def _label_line(line: str) -> bool:
    """A short axis label (``y``, ``O``, ``x``) between art lines."""
    chars = [c for c in line if not c.isspace()]
    return 0 < len(chars) <= 3 and not re.search(r"[\u4e00-\u9fff]", line) and not re.search(r"[=<>$\\]", line)


def _protected(lines: list[str]) -> list[bool]:
    """Lines inside display maths or Markdown tables are never art."""
    keep = [False] * len(lines)
    in_math = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if in_math:
            keep[index] = True
            if in_math in stripped:
                in_math = None
            continue
        for opening, closing in (("$$", "$$"), ("\\[", "\\]"), ("\\begin{", "\\end{")):
            if stripped.startswith(opening):
                keep[index] = True
                rest = stripped[len(opening):]
                if closing not in rest:
                    in_math = closing
                break
    index = 0
    while index < len(lines):
        if _TABLE_ROW.match(lines[index]):
            end = index
            while end < len(lines) and _TABLE_ROW.match(lines[end]) or end < len(lines) and _TABLE_RULE.match(lines[end]):
                end += 1
            if any(_TABLE_RULE.match(line) for line in lines[index:end]):
                for row in range(index, end):
                    keep[row] = True
            index = max(end, index + 1)
        else:
            index += 1
    return keep


def _art_spans(lines: list[str], *, minimum: int = 3) -> list[tuple[int, int]]:
    """``[start, end)`` line spans holding at least ``minimum`` art lines in a row."""
    keep = _protected(lines)
    spans, index = [], 0
    while index < len(lines):
        if keep[index] or not _art_line(lines[index]):
            index += 1
            continue
        start = end = index
        art = 0
        while end < len(lines) and not keep[end] and (_art_line(lines[end]) or _label_line(lines[end])):
            art += _art_line(lines[end])
            end += 1
        if art >= minimum:
            while start > 0 and not keep[start - 1] and _label_line(lines[start - 1]):
                start -= 1
            spans.append((start, end))
        index = max(end, index + 1)
    return spans


def _art_runs(lines: list[str], *, minimum: int) -> bool:
    return bool(_art_spans(lines, minimum=minimum))


def sanitize_figures(text: str) -> tuple[str, int]:
    """Return ``(clean_text, removed_count)``; see the module docstring."""
    source = str(text or "")
    removed = 0
    placeholders: list[str] = []

    def hold(chunk: str) -> str:
        placeholders.append(chunk)
        return f"\x00{len(placeholders) - 1}\x00"

    def fence(match: re.Match) -> str:
        nonlocal removed
        if _drawing_fence(match.group(2), match.group(3)):
            removed += 1
            return FIGURE_NOTE
        return hold(match.group(0))  # an ordinary code block stays untouched

    def drop(match: re.Match) -> str:
        nonlocal removed
        removed += 1
        return FIGURE_NOTE

    clean = _FENCE.sub(fence, source)
    clean = _LATEX_PICTURE.sub(drop, clean)
    clean = _MARKDOWN_IMAGE.sub(drop, clean)
    clean = _HTML_FIGURE.sub(drop, clean)
    lines = clean.split("\n")
    for start, end in reversed(_art_spans(lines)):
        removed += 1
        lines[start:end] = [FIGURE_NOTE]
    clean = "\n".join(lines)
    clean = re.sub(r"\x00(\d+)\x00", lambda m: placeholders[int(m.group(1))], clean)
    # A stray fence name outside any block can still not become a canvas.
    clean = _TOKEN.sub("图示", clean)
    if removed:
        clean = re.sub(r"(?:\s*" + re.escape(FIGURE_NOTE) + r")+", lambda m: "\n\n" + FIGURE_NOTE, clean)
        clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    return clean, removed


__all__ = ["FIGURE_NOTE", "sanitize_figures"]
