"""Persisted, non-sensitive Tutor personality preferences."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field


PERSONALITY_PRESETS = {
    "patient": {"label": "耐心引导", "instruction": "语气耐心温和，先肯定有效尝试，再用一个小问题推进。"},
    "socratic": {"label": "苏格拉底式", "instruction": "优先用简短追问帮助学生自己发现下一步，不连续给出结论。"},
    "concise": {"label": "简洁直接", "instruction": "句子简短，只保留当前一步需要的信息。"},
    "detailed": {"label": "细致讲解", "instruction": "在披露边界内解释每一步缘由，并检查学生是否理解。"},
    "custom": {"label": "自定义", "instruction": ""},
}


class TutorPreferences(BaseModel):
    personality: str = "patient"
    custom_instruction: str = Field(default="", max_length=1000)


class TutorPreferenceService:
    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._current = TutorPreferences()
        if path is not None and path.is_file():
            try:
                self._current = TutorPreferences.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass

    def current(self) -> TutorPreferences:
        return self._current.model_copy()

    def public_settings(self) -> dict:
        return {
            **self._current.model_dump(),
            "presets": [{"id": key, "label": value["label"]} for key, value in PERSONALITY_PRESETS.items()],
        }

    def instruction(self) -> str:
        preset = PERSONALITY_PRESETS.get(self._current.personality, PERSONALITY_PRESETS["patient"])
        if self._current.personality == "custom":
            return self._current.custom_instruction.strip() or PERSONALITY_PRESETS["patient"]["instruction"]
        return preset["instruction"]

    def update(self, personality: str, custom_instruction: str = "") -> dict:
        if personality not in PERSONALITY_PRESETS:
            raise ValueError("未知的 Tutor 风格。")
        current = TutorPreferences(personality=personality, custom_instruction=custom_instruction.strip())
        self._current = current
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(current.model_dump(), ensure_ascii=False, indent=2) + "\n"
            fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
        return self.public_settings()
