"""Public desktop projections validated by Pydantic and exported as OpenAPI.

Edit these contracts with their route projection; regenerate web API types.
WebSocket events keep a separate runtime projection boundary.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict
from typing_extensions import NotRequired, TypedDict


class EvidenceSummary(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    independent: int
    assisted: int
    post_solution: int
    diagnostic: int
    ungradable: int
    status: NotRequired[str]


class ConfigurationReceipt(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    provider_id: NotRequired[str]
    revision: NotRequired[int]
    current_revision: NotRequired[int]
    epoch: NotRequired[str]
    operation_id: NotRequired[str]
    accepted: NotRequired[bool]
    persisted: NotRequired[bool]
    persistence_error: NotRequired[
        Literal["config_write_failed"] | Literal["persistence_unavailable"] | None
    ]


class ConfigurationOperation(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    revision: NotRequired[int]
    epoch: NotRequired[str]
    operation_id: NotRequired[str]


class DesktopSettingsProvider_configsValue(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    vision_mode: NotRequired[Literal["auto"] | Literal["enabled"] | Literal["disabled"]]
    model: str
    base_url: str
    has_api_key: bool
    key_masked: str | None


class DesktopSettings(ConfigurationReceipt):
    __pydantic_config__ = ConfigDict(extra="forbid")
    initial_assessment_required: NotRequired[bool]
    vision_mode: NotRequired[Literal["auto"] | Literal["enabled"] | Literal["disabled"]]
    preset_id: str
    model: str
    base_url: str
    is_configured: bool
    onboarding_completed: bool
    key_masked: str | None
    connection_status: NotRequired[
        Literal["unconfigured"]
        | Literal["configured"]
        | Literal["connecting"]
        | Literal["success"]
        | Literal["failure"]
    ]
    provider_configs: NotRequired[dict[str, DesktopSettingsProvider_configsValue]]


class ProviderPreset(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    preset_id: str
    label: str
    custom: bool
    default_model: NotRequired[str]
    base_url: NotRequired[str]
    requires_api_key: NotRequired[bool]
    editable_base_url: NotRequired[bool]
    local: NotRequired[bool]


class TutorSettingsPresetsItem(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    id: str
    label: str


class TutorSettings(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    personality: str
    custom_instruction: str
    presets: list[TutorSettingsPresetsItem]


class SettingsSaveResult(ConfigurationReceipt):
    __pydantic_config__ = ConfigDict(extra="forbid")
    initial_assessment_required: NotRequired[bool]
    vision_mode: NotRequired[Literal["auto"] | Literal["enabled"] | Literal["disabled"]]
    preset_id: str
    model: str
    base_url: str
    key_masked: str | None
    is_configured: bool
    onboarding_completed: bool
    connection_status: NotRequired[
        Literal["unconfigured"]
        | Literal["configured"]
        | Literal["connecting"]
        | Literal["success"]
        | Literal["failure"]
    ]


EmbeddingProvider = Literal["local"] | Literal["cloud"]


EmbeddingStatus = (
    Literal["disabled"]
    | Literal["local_ready"]
    | Literal["cloud_configured"]
    | Literal["incomplete"]
)


LocalEmbeddingDownloadStatus = (
    Literal["not_downloaded"]
    | Literal["downloading"]
    | Literal["ready"]
    | Literal["failed"]
)


class LocalEmbeddingModel(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    model_id: str
    label: str
    dimension: int
    size_label: str
    source: str


class EmbeddingSettings(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    enabled: bool
    provider: EmbeddingProvider
    local_model_id: str
    local_models: list[LocalEmbeddingModel]
    local_download_status: LocalEmbeddingDownloadStatus
    local_download_error: str | None
    cloud_base_url: str
    cloud_model: str
    cloud_has_api_key: bool
    cloud_key_masked: str | None
    status: EmbeddingStatus
    status_label: str
    runtime_reason: str | None
    reindex_required: bool


class EmbeddingTestResult(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    ok: bool
    message: str


class TestConnectionResult(ConfigurationReceipt):
    __pydantic_config__ = ConfigDict(extra="forbid")
    status: Literal["ok"] | Literal["error"]
    message: str
    resolved_model: NotRequired[str]


CheckValue = Literal["ok"] | Literal["degraded"] | Literal["error"]


ReadinessStatus = Literal["READY"] | Literal["DEGRADED"] | Literal["BLOCKED"]


class Readiness(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    status: ReadinessStatus
    checks: dict[str, CheckValue]
    reasons: dict[str, str]


DocumentStatus = (
    Literal["importing"]
    | Literal["parsing"]
    | Literal["ready"]
    | Literal["ready_with_warnings"]
    | Literal["needs_ocr"]
    | Literal["failed"]
)


class DesktopDocument(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    document_id: str
    filename: str
    mime_type: str
    status: DocumentStatus
    retrieval_enabled: bool
    size_bytes: int
    page_count: int
    chunk_count: int
    image_count: int
    empty_page_count: int
    parse_warning: str | None
    created_at: str
    error: str | None
    conversation_ids: NotRequired[list[str]]
    conversation_titles: NotRequired[dict[str, str]]
    is_global: NotRequired[bool]


MemorySourceType = (
    Literal["USER_EXPLICIT"] | Literal["MODEL_INFERRED"] | Literal["USER_CONFIRMED"]
)


class DesktopMemory(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    memory_id: str
    memory_type: str
    subject: str
    predicate: str
    object_json: dict[str, Any]
    source_type: MemorySourceType
    confidence: float
    retrieval_enabled: bool
    created_at: str
    updated_at: str


OfferStatus = (
    Literal["ACTIVE"] | Literal["ACCEPTED"] | Literal["EXPIRED"] | Literal["REVOKED"]
)


class PracticeOfferResult_summaryVariant1(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    independent_correct: int
    first_free_response: NotRequired[int]
    diagnostic_correct: NotRequired[int]
    helped: int
    observations: int


class PracticeOffer(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    purpose: NotRequired[str]
    history_cutoff_seq: NotRequired[int | None]
    basis: NotRequired[dict[str, Any] | None]
    child_cycle_id: NotRequired[str | None]
    offer_id: str
    status: OfferStatus
    skill_labels: list[str]
    concept_labels: list[str]
    difficulty: int | None
    offered_at: str
    expires_at: str
    parent_cycle_id: str
    title: NotRequired[str]
    reason: NotRequired[str]
    observation_goal: NotRequired[str]
    response_mode: NotRequired[Literal["free_response"] | Literal["single_choice"]]
    observation_kind: NotRequired[
        Literal["independent_transfer"] | Literal["diagnostic"]
    ]
    question_count: NotRequired[int]
    display_status: NotRequired[
        Literal["pending"]
        | Literal["in_progress"]
        | Literal["completed"]
        | Literal["later"]
        | Literal["history"]
    ]
    feedback: NotRequired[Literal["later"] | Literal["not_relevant"] | None]
    resume_session_id: NotRequired[str | None]
    evidence_href: NotRequired[str]
    update_reason: NotRequired[str | None]
    evidence_ids: NotRequired[list[str]]
    result_summary: NotRequired[PracticeOfferResult_summaryVariant1 | None]


BootstrapStepStatus = Literal["ok"] | Literal["degraded"] | Literal["blocked"]


class BootstrapStep(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    key: str
    label: str
    status: BootstrapStepStatus
    detail: str | None


class BootstrapPayload(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    readiness: ReadinessStatus
    phase: str
    reason: str | None
    steps: list[BootstrapStep]


ModelErrorKind = (
    Literal["response_incomplete"]
    | Literal["request_rejected"]
    | Literal["quota_exceeded"]
    | Literal["rate_limited"]
    | Literal["provider_error"]
    | Literal["credential_invalid"]
    | Literal["network_unavailable"]
    | Literal["provider_unsupported"]
    | Literal["model_unavailable"]
    | Literal["gateway_disabled"]
)


class ModelTestResult(ConfigurationReceipt):
    __pydantic_config__ = ConfigDict(extra="forbid")
    ok: bool
    error_kind: ModelErrorKind | None
    message: str | None
    resolved_model: NotRequired[str]


BackupIntegrity = Literal["ok"] | Literal["unknown"]


class BackupRecord(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    path: str
    created_at: str
    size_bytes: int
    integrity: BackupIntegrity
    sha256_prefix: str


class BackupsListPolicy(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    retention_limit: int
    mode: str


class BackupsList(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    backups: list[BackupRecord]
    backup_dir: str
    policy: BackupsListPolicy


class BackupActionResultVariant1(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    ok: Literal[True]
    backup: BackupRecord


class BackupActionResultVariant2(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    ok: Literal[False]
    message: str


BackupActionResult = BackupActionResultVariant1 | BackupActionResultVariant2


class BackupVerifyResultVariant1(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    ok: Literal[True]


class BackupVerifyResultVariant2(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    ok: Literal[False]
    message: str


BackupVerifyResult = BackupVerifyResultVariant1 | BackupVerifyResultVariant2


class BackupRestoreResultVariant1(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    ok: Literal[True]
    restart_required: Literal[True]
    message: str


class BackupRestoreResultVariant2(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    recovery_required: NotRequired[bool]
    ok: Literal[False]
    message: str


BackupRestoreResult = BackupRestoreResultVariant1 | BackupRestoreResultVariant2


class SkillSummaryCountsValue(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    correct: int
    incorrect: int


class SkillSummary(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    code: str
    label: str
    mastery: float | None
    grade_band: str | None
    evidence_summary: NotRequired[EvidenceSummary | None]
    evidence_status: NotRequired[str]
    observation: NotRequired[str]
    counts: NotRequired[dict[str, SkillSummaryCountsValue]]
    last_checked_at: NotRequired[str | None]
    evidence_count: NotRequired[int]
    joint_task_evidence: NotRequired[int]
    next_href: NotRequired[str]
    next_action: NotRequired[str]


class ItemErrorObservation(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    rule_id: str
    label: str
    event_id: str
    assessment_id: str
    cycle_id: str
    related_skill_ids: list[str]
    last_seen_at: str | None
    status: Literal["unlocalized"] | Literal["corrected_later"]
    correction_event_id: str | None


class StudentSummaryMisconceptionsItem(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    rule_id: str
    label: str
    skill_ids: list[str]
    last_seen_at: str | None


class StudentSummaryCoverage(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    supported_skills: int
    observed_skills: int


class StudentSummary(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    last_event_seq: NotRequired[int]
    model_status: NotRequired[str]
    evidence_summary: NotRequired[EvidenceSummary]
    skills: list[SkillSummary]
    total_attempts: int
    active_misconceptions: int
    misconceptions: NotRequired[list[StudentSummaryMisconceptionsItem]]
    item_error_observations: NotRequired[list[ItemErrorObservation]]
    schema_version: NotRequired[str]
    has_conversations: NotRequired[bool]
    has_independent_evidence: NotRequired[bool]
    coverage: NotRequired[StudentSummaryCoverage]


class LearningEvidence(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    event_id: str
    event_seq: int
    cycle_id: str
    occurred_at: str
    skill_ids: list[str]
    problem_text: str
    student_response: str
    correctness: str | None
    evidence_kind: str
    completion_scope: str
    first_target: bool
    excluded: bool
    session_id: str | None


class EvidencePage(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    items: list[LearningEvidence]
    next_cursor: int | None


class PurgeDocumentsResult(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    ok: bool
    documents_soft_deleted: int
    chunks_removed: int
    vectors_cleared: int
    index_builds_removed: int
    storage_files_removed: int


class PurgeMemoryResult(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    ok: bool
    memories_soft_deleted: int


class EducationalHistoryResultProjectionVariant1(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    projection_version: int
    estimator_version: str
    evidence_remaining: int
    observations_remaining: int


class EducationalHistoryResult(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    teaching_contexts_cleared: int
    ok: bool
    deleted_rows: int
    by_table: dict[str, int]
    kept_skeleton_tables: list[str]
    projection: EducationalHistoryResultProjectionVariant1 | None


class RebuildIndexesResultDocumentsValue(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    status: Literal["rebuilt"] | Literal["unavailable"] | Literal["no_chunks"]
    reason: NotRequired[str]
    index_version: int | None


class RebuildIndexesResult(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    ok: bool
    documents: dict[str, RebuildIndexesResultDocumentsValue]


class BinaryEvidenceCounts(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    correct: int
    incorrect: int


class ExportEvidenceCounts(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    independent: BinaryEvidenceCounts
    assisted: BinaryEvidenceCounts
    post_solution: BinaryEvidenceCounts
    diagnostic: BinaryEvidenceCounts
    ungradable: int
    step_correct: int
    joint_task_evidence: int
    duplicate_responses: int
    repeat_attempts: NotRequired[int]


class ExportSkill(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    skill_id: str
    evidence_status: str
    evidence_summary: ExportEvidenceCounts


class ExportLearningLoop(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    domain: str
    phase: str
    due_at: str | None
    review_round: int
    diagnostic_status: str
    evidence: dict[str, int]


class ExportMisconception(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    rule_id: str
    label: NotRequired[str]
    skill_ids: NotRequired[list[str]]
    last_seen_at: NotRequired[str | None]
    status: str
    confidence: float | None


class StudentExportMeta(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    schema_version: str
    exported_at: str
    student_id: str


class StudentExportStudent_summary(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    learning_loop: NotRequired[list[ExportLearningLoop]]
    model_status: NotRequired[str]
    total_attempts: int
    estimator_version: str
    projection_version: int | None
    skills: list[ExportSkill]
    active_misconceptions: list[ExportMisconception]
    item_error_observations: NotRequired[list[ItemErrorObservation]]


class StudentExport(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    meta: StudentExportMeta
    documents: list[DesktopDocument]
    memory: list[DesktopMemory]
    student_summary: StudentExportStudent_summary


class CostSettingsInput(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    input_price_per_mtok: float | None
    output_price_per_mtok: float | None
    currency: str
    daily_budget: float | None
    daily_token_budget: int | None


class CostSettingsToday(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")
    date: str
    tokens: int
    cost: float
    currency: str


class CostSettings(CostSettingsInput):
    __pydantic_config__ = ConfigDict(extra="forbid")
    today: CostSettingsToday
    over_budget: bool


PUBLIC_CONTRACTS = [
    "EvidenceSummary",
    "ConfigurationReceipt",
    "ConfigurationOperation",
    "DesktopSettings",
    "ProviderPreset",
    "TutorSettings",
    "SettingsSaveResult",
    "EmbeddingProvider",
    "EmbeddingStatus",
    "LocalEmbeddingDownloadStatus",
    "LocalEmbeddingModel",
    "EmbeddingSettings",
    "EmbeddingTestResult",
    "TestConnectionResult",
    "CheckValue",
    "ReadinessStatus",
    "Readiness",
    "DocumentStatus",
    "DesktopDocument",
    "MemorySourceType",
    "DesktopMemory",
    "OfferStatus",
    "PracticeOffer",
    "BootstrapStepStatus",
    "BootstrapStep",
    "BootstrapPayload",
    "ModelErrorKind",
    "ModelTestResult",
    "BackupIntegrity",
    "BackupRecord",
    "BackupsList",
    "BackupActionResult",
    "BackupVerifyResult",
    "BackupRestoreResult",
    "SkillSummary",
    "ItemErrorObservation",
    "StudentSummary",
    "LearningEvidence",
    "EvidencePage",
    "PurgeDocumentsResult",
    "PurgeMemoryResult",
    "EducationalHistoryResult",
    "RebuildIndexesResult",
    "ExportSkill",
    "ExportMisconception",
    "StudentExport",
    "CostSettingsInput",
    "CostSettings",
]
