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
from mathtutor.release_config import RELEASE_CONFIG


def test_release_config_freezes_authoritative_runtime_contracts() -> None:
    from alembic.script import ScriptDirectory
    from mathtutor.infrastructure.migrate import alembic_config
    assert ScriptDirectory.from_config(alembic_config()).get_current_head() == MIGRATION_HEAD
    assert RELEASE_CONFIG.app_version == "0.6.2"
    assert RELEASE_CONFIG.schema_version == SCHEMA_VERSION
    assert RELEASE_CONFIG.migration_head == MIGRATION_HEAD == "024"
    assert RELEASE_CONFIG.curriculum_active_version == StaticCurriculumProvider.VERSION_CODE
    assert RELEASE_CONFIG.curriculum_default_version == StaticCurriculumProvider.VERSION_CODE
    assert RELEASE_CONFIG.verifier_version == AUTHORITATIVE_VERIFIER_VERSION
    assert RELEASE_CONFIG.estimator_version == ESTIMATOR_VERSION
    assert RELEASE_CONFIG.parser_version == PARSER_VERSION
    assert RELEASE_CONFIG.chunker_version == CHUNKER_VERSION
    assert RELEASE_CONFIG.retrieval_version == RetrievalPolicy.POLICY_VERSION
    assert RELEASE_CONFIG.release_policy_version == RELEASE_POLICY_VERSION
    assert dict(RELEASE_CONFIG.stage_policy_versions) == {
        "high": "2",
        "middle": "2",
        "primary": "2",
    }


def test_release_config_public_manifest_is_secret_free_and_json_safe() -> None:
    manifest = RELEASE_CONFIG.public_manifest()
    assert manifest["migration_head"] == "024"
    assert manifest["stage_policy_versions"] == {
        "high": "2",
        "middle": "2",
        "primary": "2",
    }
    assert not any("key" in field.lower() or "secret" in field.lower() for field in manifest)
