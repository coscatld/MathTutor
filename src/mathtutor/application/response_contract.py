"""Read explicit presentation requests without changing a student's answer.

These are output constraints, not mathematical authority.  A contract can guide
generation and flag a violation, but never truncates a proof, chooses a label,
or rewrites a conclusion to make an answer appear compliant.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}
_NUMBER = r"(?:\d{1,4}|zero|one|two|three|four|five|six|seven|eight|nine|ten|[零一二两三四五六七八九十])"
_HISTORY = re.compile(
    r"(?:^|\n)\s*(?:conversation|dialog(?:ue)?\s+history|对话(?:记录|历史)?)\s*[:：]", re.I)
_CONTEXT = re.compile(
    r"(?:^|\n)\s*(?:problem|question|student(?:[’']s)?\s+(?:solution|work)|题目|问题|学生(?:解答|步骤))\s*[:：]", re.I)
_LATEST = re.compile(r"(?:^|\n)\s*(?:student[’']s\s+latest\s+message|学生(?:的)?最新(?:消息|问题))\s*[:：]", re.I)
_OUTPUT_SLOT = re.compile(
    r"(?:^|\n)\s*(?:teacher|tutor|assistant|response|教师|老师|助教|回答|答复)"
    r"\s*[（(]([^\n]*)[）)]\s*[:：]\s*$", re.I)
_REFERENCE_FIELD = re.compile(
    r"(?:^|\n)\s*(?:problem|question|conversation|student(?:[’']s)?\s*(?:solution|work)?|teacher|tutor|assistant|"
    r"题目|问题|学生(?:解答|步骤)?|老师|教师|对话(?:记录|历史)?)\s*[:：][^\n]*", re.I)
_TAIL_DIRECTIVE = re.compile(
    r"(?:^|[.!?。！？])\s*(?:please\s+)?(?:(?:do\s+not|don[’']t)\s+)?"
    r"(?:write\b|answer\b|reply\b|respond\b|return\b|output\b|use\b|limit\b|keep\b|maximum\b|请|只|不要|用|使用)", re.I)
_QUOTED = re.compile(r'“[^”]*”|‘[^’]*’|「[^」]*」|『[^』]*』|"[^"\n]*"|(?<!\w)\x27[^\x27\n]*\x27(?!\w)')


def _instruction_surface(text: str) -> str:
    """Keep the caller's instructions and an empty final output-role heading.

    Embedded teacher turns are student-provided evidence, so their formatting
    requests cannot override the caller.  A final ``Teacher (...):`` with no
    content, however, explicitly specifies the response the caller requests.
    """
    history = _HISTORY.search(text)
    latest = list(_LATEST.finditer(text))
    boundaries = [match.start() for match in (history, _CONTEXT.search(text)) if match]
    if latest:
        boundaries.append(latest[-1].start())
    surface = text[:min(boundaries)] if boundaries else text
    if latest:
        tail = text[latest[-1].end():]
        following_references = [match.start() for match in (_HISTORY.search(tail), _CONTEXT.search(tail)) if match]
        surface += "\n" + (tail[:min(following_references)] if following_references else tail)
    slot = _OUTPUT_SLOT.search(text)
    if slot:
        surface += "\n" + slot.group(1)
    # In a question/answer template the final empty answer slot belongs to the
    # current request. Earlier completed examples remain reference material.
    answer_slot = re.search(r"(?:^|\n)\s*(?:A|answer|回答)\s*[:：]\s*$", text, re.I)
    if answer_slot:
        questions = list(re.finditer(r"(?:^|\n)\s*(?:Q|current\s+request|当前请求)\s*[:：]", text[:answer_slot.start()], re.I))
        if questions:
            surface += "\n" + text[questions[-1].end():answer_slot.start()]
    # A caller may place a current instruction on its own line after a student
    # work block. A completed Teacher:/Student: line itself stays reference
    # data, as do narrative continuation lines without a direct request.
    reference_fields = list(_REFERENCE_FIELD.finditer(text))
    if reference_fields:
        tail = text[reference_fields[-1].end():]
        surface += "\n" + "\n".join(line for line in tail.splitlines() if _TAIL_DIRECTIVE.search(line))
    return _QUOTED.sub(" ", surface)


def _number(value: str) -> int:
    return int(value) if value.isdigit() else _NUMBERS[value.lower()]


def _direct_limit(surface: str, start: int) -> bool:
    """Avoid reading a story's sentence/word quantities as caller commands."""
    before = re.split(r"[.!?。！？;；\n:：]", surface[:start])[-1].strip(" \t-*(（")
    if not before:
        return True  # e.g. an empty output heading's "maximum two sentences"
    return bool(re.match(
        r"(?:please\b|you\b|your\b|(?:the\s+)?(?:answer|response|reply)\b|"
        r"use\b|write\b|reply\b|respond\b|answer\b|ask\b|give\b|provide\b|"
        r"keep\b|limit\b|help\b|explain\b|describe\b|summarize\b|solve\b|in\b|with\b|你|请|回答|回复|答复|输出|用|使用|此轮|本轮|每次)",
        before, re.I))


def _affirmative(surface: str, start: int) -> bool:
    """A negated format request is not permission to impose that format."""
    before = re.split(r"[.!?。！？;；\n,，]", surface[:start])[-1]
    return not re.search(r"\b(?:do\s+not|don[’']t|never|avoid|instead\s+of)\b|不要|不用|别|不必|无需|不需要", before, re.I)


@dataclass(frozen=True)
class ResponseContract:
    max_sentences: int | None = None
    exact_sentences: int | None = None
    max_questions: int | None = None
    max_words: int | None = None
    max_characters: int | None = None
    language: str | None = None
    choices: tuple[str, ...] = ()
    json_only: bool = False

    @property
    def strict_presentation(self) -> bool:
        return bool(self.choices or self.json_only or self.max_sentences is not None
                    or self.exact_sentences is not None or self.max_words is not None
                    or self.max_characters is not None)

    def system_instruction(self) -> str:
        """Put concrete current-request limits after the default style prompt."""
        limits: list[str] = []
        if self.exact_sentences is not None:
            limits.append(f"Use exactly {self.exact_sentences} sentences.")
        elif self.max_sentences is not None:
            limits.append(f"Use at most {self.max_sentences} sentences.")
        if self.max_questions is not None:
            limits.append(f"Ask at most {self.max_questions} questions; do not combine multiple questions in one sentence.")
        if self.max_words is not None:
            limits.append(f"Use at most {self.max_words} words.")
        if self.max_characters is not None:
            limits.append(f"Use at most {self.max_characters} non-whitespace characters.")
        if self.language:
            limits.append(f"Answer in {self.language}.")
        if self.choices:
            limits.append("The entire answer must be exactly one of: " + ", ".join(self.choices) + ".")
        if self.json_only:
            limits.append("Return only valid JSON, without Markdown fences, a preface, or a closing explanation.")
        if not limits:
            return ""
        return ("\nCurrent response presentation requirements (override default paragraph and follow-up-question style):\n"
                + "\n".join(limits)
                + "\nAll encouragement, explanations, and closing questions count toward these limits. "
                "Select the information needed for the student's current request; preserve necessary conditions and mathematical correctness. "
                "Do not append a second task, practice exercise, or unsolicited explanation.")

    def violations(self, answer: str) -> tuple[str, ...]:
        """Report observable failures; never manufacture compliance by editing."""
        violations: list[str] = []
        sentences = sentence_count(answer)
        if self.exact_sentences is not None and sentences != self.exact_sentences:
            violations.append("sentence_count")
        elif self.max_sentences is not None and sentences > self.max_sentences:
            violations.append("sentence_limit")
        if self.max_questions is not None and question_count(answer) > self.max_questions:
            violations.append("question_limit")
        if self.max_words is not None and len(re.findall(r"\b[\w]+(?:['’-][\w]+)*\b", answer)) > self.max_words:
            violations.append("word_limit")
        if self.max_characters is not None and len(re.sub(r"\s", "", answer)) > self.max_characters:
            violations.append("character_limit")
        if self.choices and answer.strip() not in self.choices:
            violations.append("choice_format")
        if self.json_only:
            import json
            try:
                json.loads(answer)
            except (ValueError, TypeError):
                violations.append("json_format")
        return tuple(violations)


def extract_response_contract(text: str) -> ResponseContract:
    """Recognize conservative, explicit bilingual constraints from a request."""
    surface = _instruction_surface(str(text or ""))
    maximum: dict[str, int] = {}
    exact_sentences = None
    for match in re.finditer(
        rf"\b(?:at\s+most|no\s+more\s+than|maximum(?:\s+of)?|up\s+to|only|exactly)\s+({_NUMBER})\s+(sentences?|questions?|words?|characters?)\b",
        surface, re.I,
    ):
        if not _direct_limit(surface, match.start()) or not _affirmative(surface, match.start()):
            continue
        value, unit = _number(match.group(1)), match.group(2).lower().rstrip("s")
        if match.group().lower().startswith("exactly") and unit == "sentence":
            exact_sentences = value
        else:
            maximum[unit] = min(maximum.get(unit, value), value)
    # A quantity in a story ("she writes two sentences") is not an output
    # instruction. Require a response-length verb for this alternative form.
    for match in re.finditer(
        rf"\b(?:limit\s+(?:your\s+)?(?:answer|response|reply)\s+to|keep\s+(?:your\s+)?(?:answer|response|reply|it)\s+to)\s+({_NUMBER})\s+sentences?\b",
        surface, re.I,
    ):
        if not _direct_limit(surface, match.start()) or not _affirmative(surface, match.start()):
            continue
        value = _number(match.group(1))
        maximum["sentence"] = min(maximum.get("sentence", value), value)
    for match in re.finditer(
        rf"(?:最多|不超过|至多|不多于|只(?:能)?(?:用|写|问|提)?|仅(?:用|写|问|提)?|恰好)\s*({_NUMBER})\s*(?:个)?(句(?:话|子)?|问题|字|词)", surface,
    ):
        if not _direct_limit(surface, match.start()) or not _affirmative(surface, match.start()):
            continue
        value = _number(match.group(1))
        unit = ("sentence" if match.group(2).startswith("句") else "question" if match.group(2) == "问题"
                else "character" if match.group(2) == "字" else "word")
        if match.group().startswith("恰好") and unit == "sentence":
            exact_sentences = value
        else:
            maximum[unit] = min(maximum.get(unit, value), value)
    if any(_direct_limit(surface, match.start()) for match in re.finditer(
        r"\b(?:do\s+not|don[’']t|never)\s+ask\s+(?:any\s+)?questions?\b|不要(?:再)?提问|不(?:要|用)问(?:我|问题)",
        surface, re.I)):
        maximum["question"] = 0
    language = None
    language_matches = [match for match in re.finditer(
        r"\b(?:answer|reply|respond|write|explain)(?:\s+(?:this|it|your\s+(?:answer|response)))?\s+in\s+(English|Chinese|French|Spanish|German|Japanese)\b"
        r"|(?:请)?(?:用|使用)(中文|英文|英语|汉语|法语|西班牙语|德语|日语)(?:回答|回复|作答|解释)", surface, re.I)
        if _affirmative(surface, match.start())]
    if language_matches:
        match = language_matches[-1]
        names = {"中文": "Chinese", "汉语": "Chinese", "英文": "English", "英语": "English",
                 "法语": "French", "西班牙语": "Spanish", "德语": "German", "日语": "Japanese"}
        language = names.get(match.group(2), match.group(1).title() if match.group(1) else None)
    # An explicit closed answer set is a presentation rule.  Do not infer the
    # correct choice or trim a longer model answer to whichever label it contains.
    choices: tuple[str, ...] = ()
    choice_matches = [match for match in re.finditer(
        r"\b(?:write|answer|reply|respond|return|output)\s+(?:with\s+)?only\s+(Yes\s+or\s+No|True\s+or\s+False)\b",
        surface, re.I) if _affirmative(surface, match.start())]
    if choice_matches:
        choice = choice_matches[-1]
        choices = tuple(re.split(r"\s+or\s+", choice.group(1), flags=re.I))
    json_only = any(_affirmative(surface, match.start()) for match in re.finditer(
        r"\b(?:return|output|respond\s+with|reply\s+with)\s+(?:only\s+(?:valid\s+)?JSON|(?:valid\s+)?JSON\s+only)\b"
        r"|(?:仅|只)(?:返回|输出)(?:有效的?)?\s*JSON", surface, re.I))
    return ResponseContract(max_sentences=maximum.get("sentence"), exact_sentences=exact_sentences,
                            max_questions=maximum.get("question"), max_words=maximum.get("word"),
                            max_characters=maximum.get("character"), language=language,
                            choices=choices, json_only=json_only)


_MATH_OR_CODE = re.compile(r"```[\s\S]*?```|`[^`\n]+`|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]|\$\$[\s\S]*?\$\$|(?<!\\)\$[^$\n]+\$")


def _prose(text: str) -> str:
    # Replace a formula with visible content so a formula-only answer still
    # counts as one sentence, while decimal dots and factorials do not split it.
    return _MATH_OR_CODE.sub(" MATH ", text)


def sentence_count(text: str) -> int:
    """Count sentence terminators plus a trailing prose fragment.

    Semicolons and line breaks do not become artificial sentence boundaries.
    A punctuation-free list is therefore not claimed to contain one sentence
    per item. This observable check does not replace semantic format review.
    """
    prose = _prose(text).strip()
    if not prose:
        return 0
    prose = re.sub(r"(?m)^\s*(?:[-*+]\s+)?\d+[.)、]\s+", "", prose)
    prose = re.sub(r"https?://[^\s)\]>]+", "URL", prose)
    prose = re.sub(r"\b(?:e\.g|i\.e)\.", "ABBREVIATION", prose, flags=re.I)
    prose = re.sub(r"\b(?:Mr|Mrs|Ms|Dr|Prof|vs)\.", "TITLE", prose, flags=re.I)
    prose = re.sub(r"\b(?:[A-Z]\.){2,}", "INITIALS", prose)
    prose = re.sub(r"(?<=\d)\.(?=\d)", "DECIMAL", prose)
    pieces = re.split(r"[。！？.!?]+(?:[’'\"”）)]*)(?:\s*|$)", prose)
    return sum(bool(re.search(r"[\w\u4e00-\u9fff]", piece)) for piece in pieces)


def question_count(text: str) -> int:
    # This detects explicit question marks only.  A rhetorical question without
    # one or two questions joined by 'and' still require semantic assessment.
    return len(re.findall(r"[?？]+", _prose(text)))


__all__ = ["ResponseContract", "extract_response_contract", "sentence_count", "question_count"]
