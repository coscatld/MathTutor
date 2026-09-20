"""Frozen MathTutor release contract.

These values identify persisted or authoritative runtime semantics.  They
must never be sourced from ordinary user settings: changing one requires a
deliberate release/migration decision and corresponding regression evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from mathtutor.application.context_assembler import StaticCurriculumProvider
from mathtutor.application.practice_release import RELEASE_POLICY_VERSION
from mathtutor.application.verification_backend import (
    AUTHORITATIVE_VERIFIER_VERSION,
)
from mathtutor.domain.problem import SCHEMA_VERSION
from mathtutor.domain.retrieval_policy import RetrievalPolicy
from mathtutor.infrastructure.chunking import CHUNKER_VERSION
from mathtutor.infrastructure.document_parser import PARSER_VERSION
from mathtutor.infrastructure.migrate import MIGRATION_HEAD
from mathtutor.learning.estimator import ESTIMATOR_VERSION
from mathtutor.pedagogy.stage_policy import STAGE_POLICIES


@dataclass(frozen=True, slots=True)
class ReleaseConfig:
    """Immutable, secret-free release identity used by API and manifests."""

    app_version: str
    schema_version: str
    migration_head: str
    curriculum_active_version: str
    curriculum_default_version: str
    verifier_version: str
    estimator_version: str
    parser_version: str
    chunker_version: str
    retrieval_version: str
    release_policy_version: str
    stage_policy_versions: tuple[tuple[str, str], ...]

    def public_manifest(self) -> dict[str, Any]:
        """Return a JSON-safe copy; this contract contains no user data."""

        payload = asdict(self)
        payload["stage_policy_versions"] = dict(self.stage_policy_versions)
        return payload


RELEASE_CONFIG = ReleaseConfig(
    app_version="0.4.2",
    schema_version=SCHEMA_VERSION,
    migration_head=MIGRATION_HEAD,
    curriculum_active_version=StaticCurriculumProvider.VERSION_CODE,
    curriculum_default_version=StaticCurriculumProvider.VERSION_CODE,
    verifier_version=AUTHORITATIVE_VERIFIER_VERSION,
    estimator_version=ESTIMATOR_VERSION,
    parser_version=PARSER_VERSION,
    chunker_version=CHUNKER_VERSION,
    retrieval_version=RetrievalPolicy.POLICY_VERSION,
    release_policy_version=RELEASE_POLICY_VERSION,
    stage_policy_versions=tuple(
        sorted((stage, policy.version) for stage, policy in STAGE_POLICIES.items())
    ),
)


__all__ = ["RELEASE_CONFIG", "ReleaseConfig"]
