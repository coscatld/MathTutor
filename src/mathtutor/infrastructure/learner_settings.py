"""The learner's school stage (and optional grade), kept in the data dir."""
from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, model_validator

STAGE_GRADES = {"primary": ("小学", [1, 2, 3, 4, 5, 6]), "middle": ("初中", [7, 8, 9]), "high": ("高中", [10, 11, 12])}


class LearnerSettings(BaseModel):
    stage: str | None = None
    grade: int | None = None

    @model_validator(mode="after")
    def consistent(self):
        if self.stage is not None and self.stage not in STAGE_GRADES:
            raise ValueError("学段只能是小学、初中或高中")
        if self.grade is not None and (self.stage is None or self.grade not in STAGE_GRADES[self.stage][1]):
            raise ValueError("年级不属于所选学段")
        return self


class LearnerSettingsService:
    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._current = LearnerSettings()
        if path is not None and path.is_file():
            try:
                self._current = LearnerSettings.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass

    def current(self) -> LearnerSettings:
        return self._current.model_copy()

    def public(self) -> dict:
        return {**self._current.model_dump(),
                "stages": [{"stage": key, "label": label, "grades": grades} for key, (label, grades) in STAGE_GRADES.items()]}

    def update(self, stage: str | None, grade: int | None) -> dict:
        settings = LearnerSettings(stage=stage, grade=grade)
        self._current = settings
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(settings.model_dump(), ensure_ascii=False) + "\n")
        return self.public()


__all__ = ["LearnerSettings", "LearnerSettingsService", "STAGE_GRADES"]
