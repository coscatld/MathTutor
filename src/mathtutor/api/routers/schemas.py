"""Desktop schemas HTTP adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ConfigOperation(BaseModel):
    epoch: str | None = Field(default=None, max_length=64)
    revision: int | None = Field(default=None, ge=0)
    operation_id: str | None = Field(default=None, max_length=128)


class SettingsUpdate(BaseModel):
    expected_epoch: str | None = Field(default=None, max_length=64)
    expected_revision: int | None = Field(default=None, ge=0)
    operation_id: str | None = Field(default=None, max_length=128)
    preset_id: str
    api_key: str | None = None
    base_url: str = ""
    vision_mode: Literal["auto", "enabled", "disabled"] | None = None
    model: str = ""


class EmbeddingSettingsUpdate(BaseModel):
    enabled: bool = False
    provider: str = "local"
    local_model_id: str = "bge-small-zh-v1.5"
    cloud_base_url: str = ""
    cloud_api_key: str | None = Field(default=None, max_length=8192)
    cloud_model: str = ""


class LocalEmbeddingDownloadRequest(BaseModel):
    model_id: str = "bge-small-zh-v1.5"


class DocumentRename(BaseModel):
    filename: str = Field(min_length=1, max_length=255)


class TutorSettingsUpdate(BaseModel):
    personality: str = "patient"
    custom_instruction: str = Field(default="", max_length=1000)


class BackupPathRequest(BaseModel):
    """Client-supplied backup name (a bare file NAME — never a path)."""

    path: str
    #: Only needed when the key store no longer holds the backup key.
    recovery_key: str | None = Field(default=None, max_length=128)


class EncryptionUpdate(BaseModel):
    enabled: bool


class CostSettingsUpdate(BaseModel):
    input_price_per_mtok: float | None = None
    output_price_per_mtok: float | None = None
    currency: str = "CNY"
    daily_budget: float | None = None
    daily_token_budget: int | None = None


class LearnerUpdate(BaseModel):
    stage: str | None = None
    grade: int | None = None


class DocumentScopeInput(BaseModel):
    is_global: bool


class RetrievalToggle(BaseModel):
    enabled: bool
    expected_updated_at: datetime | None = None


class MemoryCreate(BaseModel):
    memory_type: str
    subject: str
    predicate: str
    object_json: dict = Field(default_factory=dict)
    confidence: float | None = None


class MemoryUpdate(BaseModel):
    object_json: dict | None = None
    predicate: str | None = None
    confidence: float | None = None
    expected_updated_at: datetime | None = None


class MemoryConfirmation(BaseModel):
    expected_updated_at: datetime | None = None
