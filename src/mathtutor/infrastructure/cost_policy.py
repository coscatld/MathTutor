"""Model cost accounting and the daily budget.

Prices are entered by the user (per million tokens); none are hard-coded,
because vendor prices change and a wrong built-in price would make every
cost figure wrong. Without a price, turns still count tokens and
``estimated_cost`` stays empty.

When today's spend (or tokens, if no price is set) reaches the daily budget,
model calls are blocked for the rest of the day and tutoring falls back to
the local template writer. Nothing here stores conversation text.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class CostSettings(BaseModel):
    input_price_per_mtok: float | None = Field(default=None, ge=0)
    output_price_per_mtok: float | None = Field(default=None, ge=0)
    currency: str = Field(default="CNY", pattern=r"^[A-Z]{3}$")
    daily_budget: float | None = Field(default=None, gt=0)
    daily_token_budget: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def prices_together(self):
        if (self.input_price_per_mtok is None) != (self.output_price_per_mtok is None):
            raise ValueError("输入和输出单价需要同时填写")
        if self.daily_budget is not None and self.input_price_per_mtok is None:
            raise ValueError("设置金额预算前需要先填写单价")
        return self

    @property
    def priced(self) -> bool:
        return self.input_price_per_mtok is not None


class CostPolicyService:
    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._current = CostSettings()
        if path is not None and path.is_file():
            try:
                self._current = CostSettings.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass

    def current(self) -> CostSettings:
        return self._current.model_copy()

    def update(self, values: dict) -> dict:
        settings = CostSettings.model_validate(values)
        self._current = settings
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(settings.model_dump(), ensure_ascii=False, indent=2) + "\n")
        return settings.model_dump()

    def cost(self, input_tokens: int, output_tokens: int) -> float | None:
        settings = self._current
        if not settings.priced:
            return None
        return round((input_tokens * settings.input_price_per_mtok
                      + output_tokens * settings.output_price_per_mtok) / 1_000_000, 6)

    def usage_today(self, rows: list[dict]) -> dict:
        today = datetime.now(timezone.utc).date().isoformat()
        rows = [r for r in rows if str(r.get("created_at", "")).startswith(today)]
        tokens = sum(r["input_tokens"] + r["output_tokens"] for r in rows)
        cost = sum((r.get("details") or {}).get("cost") or 0 for r in rows)
        return {"date": today, "tokens": tokens, "cost": round(cost, 6), "currency": self._current.currency}

    def over_budget(self, usage: dict) -> bool:
        settings = self._current
        if settings.daily_budget is not None and usage["cost"] >= settings.daily_budget:
            return True
        return settings.daily_token_budget is not None and usage["tokens"] >= settings.daily_token_budget


BUDGET_NOTICE = "今日模型预算已用完，本轮改用本地模板教学；数学核验和学习记录不受影响。"

__all__ = ["BUDGET_NOTICE", "CostPolicyService", "CostSettings"]
