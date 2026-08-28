"""SQLAlchemy Core schema for the MathTutor SQLite database (Phase 1).

Single source of truth for table shapes; the Alembic migration 001 applies
``metadata.create_all`` so runtime repositories and migrations never drift.

Key constraints encode the design contract:

- owner isolation: cycles/attempts/evidence carry ``student_id`` composite FKs;
- XOR: verification_logs subject is a solution candidate OR an attempt;
- CAS: cycles persist transitions via ``WHERE state_version = ?`` updates;
- append-only: transitions/evidence/verification/outbox have no UPDATE paths;
- outbox uniqueness: (aggregate_type, aggregate_id, aggregate_version, seq).
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()

# ---------------------------------------------------------------- runtime

users = Table(
    "users",
    metadata,
    Column("user_id", String(64), primary_key=True),
    Column("username", String(128), nullable=False, unique=True),
    Column("role", String(16), nullable=False, default="user"),
    Column("created_at", Text, nullable=False),
)

student_profiles = Table(
    "student_profiles",
    metadata,
    Column("student_id", String(64), primary_key=True),
    Column("user_id", String(64), ForeignKey("users.user_id"), nullable=False, unique=True),
    Column("created_at", Text, nullable=False),
)

learning_sessions = Table(
    "learning_sessions",
    metadata,
    Column("session_id", String(64), primary_key=True),
    Column("client_session_id", String(128), nullable=False),
    Column("student_id", String(64), ForeignKey("student_profiles.student_id"), nullable=False),
    Column("created_at", Text, nullable=False),
    # A client session name is namespaced per student (owner isolation).
    UniqueConstraint("student_id", "client_session_id", name="uq_session_owner_client"),
)

tutoring_cycles = Table(
    "tutoring_cycles",
    metadata,
    Column("cycle_id", String(64), primary_key=True),
    Column("session_id", String(64), ForeignKey("learning_sessions.session_id"), nullable=False),
    Column("student_id", String(64), ForeignKey("student_profiles.student_id"), nullable=False),
    Column("state", String(48), nullable=False),
    Column("state_version", Integer, nullable=False, default=0),
    Column("problem_id", String(64), nullable=True),
    Column("practice_offer_id", String(64), nullable=True),
    Column("created_at", Text, nullable=False),
    Column("closed_at", Text, nullable=True),
    CheckConstraint(
        "(problem_id IS NOT NULL AND practice_offer_id IS NULL)"
        " OR (problem_id IS NULL AND practice_offer_id IS NOT NULL)"
        " OR (problem_id IS NULL AND practice_offer_id IS NULL)",
        name="ck_cycle_source_xor",
    ),
)

cycle_transitions = Table(
    "cycle_transitions",
    metadata,
    Column("transition_id", String(64), primary_key=True),
    Column("cycle_id", String(64), ForeignKey("tutoring_cycles.cycle_id"), nullable=False),
    Column("from_state", String(48), nullable=False),
    Column("to_state", String(48), nullable=False),
    Column("trigger_command", String(48), nullable=False),
    Column("chosen_action", JSON, nullable=True),
    Column("prior_version", Integer, nullable=False),
    Column("new_version", Integer, nullable=False),
    Column("causation_id", String(64), nullable=True),
    Column("correlation_id", String(64), nullable=True),
    Column("idempotency_key", Text, nullable=False, default=""),
    Column("occurred_at", Text, nullable=False),
    # Append-only: repositories provide no UPDATE path for this table.
)

# ------------------------------------------------------------ math facts

problem_submissions = Table(
    "problem_submissions",
    metadata,
    Column("submission_id", String(64), primary_key=True),
    Column("student_id", String(64), ForeignKey("student_profiles.student_id"), nullable=False),
    # MVP stores the raw text; encryption at rest lands with the privacy
    # hardening step (design doc §6.1).
    Column("raw_text", Text, nullable=False),
    Column("submitted_at", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False, default=""),
)

math_problems = Table(
    "math_problems",
    metadata,
    Column("problem_id", String(64), primary_key=True),
    Column("schema_version", String(16), nullable=False),
    Column("canonicalization_version", String(16), nullable=False),
    Column("problem_type", String(32), nullable=False),
    Column("normalized_ast", JSON, nullable=False),
    Column("display_latex", Text, nullable=False),
    Column("content_hash", String(64), nullable=False, unique=True),
)

solution_candidates = Table(
    "solution_candidates",
    metadata,
    Column("candidate_id", String(64), primary_key=True),
    Column("problem_id", String(64), ForeignKey("math_problems.problem_id"), nullable=False),
    Column("steps", JSON, nullable=False),
    Column("final_answer", JSON, nullable=False),
    Column("payload_hash", String(64), nullable=False),
    Column("created_at", Text, nullable=False),
)

verification_logs = Table(
    "verification_logs",
    metadata,
    Column("log_id", String(64), primary_key=True),
    # XOR subject: solution candidate OR attempt (never both).
    Column("candidate_id", String(64), ForeignKey("solution_candidates.candidate_id"), nullable=True),
    Column("attempt_id", String(64), ForeignKey("attempts.attempt_id"), nullable=True),
    Column("problem_id", String(64), ForeignKey("math_problems.problem_id"), nullable=False),
    Column("verdict", String(32), nullable=False),
    Column("checks", JSON, nullable=False),
    Column("attestation_hash", String(64), nullable=True),
    Column("created_at", Text, nullable=False),
    CheckConstraint(
        "(candidate_id IS NOT NULL AND attempt_id IS NULL)"
        " OR (candidate_id IS NULL AND attempt_id IS NOT NULL)",
        name="ck_verification_subject_xor",
    ),
)

# ------------------------------------------------------------- education

attempt_submissions = Table(
    "attempt_submissions",
    metadata,
    Column("attempt_submission_id", String(64), primary_key=True),
    Column("student_id", String(64), ForeignKey("student_profiles.student_id"), nullable=False),
    Column("cycle_id", String(64), ForeignKey("tutoring_cycles.cycle_id"), nullable=False),
    Column("raw_text", Text, nullable=False),
    Column("submitted_at", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False, default=""),
)

attempts = Table(
    "attempts",
    metadata,
    Column("attempt_id", String(64), primary_key=True),
    Column("attempt_submission_id", String(64), ForeignKey("attempt_submissions.attempt_submission_id"), nullable=False),
    Column("student_id", String(64), ForeignKey("student_profiles.student_id"), nullable=False),
    Column("cycle_id", String(64), ForeignKey("tutoring_cycles.cycle_id"), nullable=False),
    Column("parsed_steps", JSON, nullable=False),
    Column("attempt_index", Integer, nullable=False),
    Column("payload_hash", String(64), nullable=False),
    Column("created_at", Text, nullable=False),
    # Supports the owner-bound evidence FK below.  attempt_id remains the
    # global primary key; the composite identity additionally proves that an
    # evidence row and its attempt belong to the same student.
    UniqueConstraint("attempt_id", "student_id", name="uq_attempt_owner_identity"),
)

attempt_assessments = Table(
    "attempt_assessments",
    metadata,
    Column("verification_log_id", String(64), ForeignKey("verification_logs.log_id"), primary_key=True),
    Column("attempt_id", String(64), ForeignKey("attempts.attempt_id"), nullable=False),
    Column("reference_solution_log_id", String(64), ForeignKey("verification_logs.log_id"), nullable=False),
    Column("correctness", String(16), nullable=False),
    Column("score", Float, nullable=True),
    Column("attestation_hash", String(64), nullable=False),
)

tutor_actions = Table(
    "tutor_actions",
    metadata,
    Column("action_id", String(64), primary_key=True),
    Column("cycle_id", String(64), ForeignKey("tutoring_cycles.cycle_id"), nullable=False),
    Column("student_id", String(64), ForeignKey("student_profiles.student_id"), nullable=False),
    Column("action", String(32), nullable=False),
    Column("effective_assistance_level", Integer, nullable=False),
    Column("solution_visibility", String(16), nullable=False),
    Column("target_step_index", Integer, nullable=True),
    Column("pedagogy_policy_version", Text, nullable=False, default=""),
    Column("stage_policy_version", Text, nullable=False, default=""),
    Column("disclosure_policy_version", Text, nullable=False, default=""),
    Column("created_at", Text, nullable=False),
)

assistance_issuances = Table(
    "assistance_issuances",
    metadata,
    Column("issuance_id", String(64), primary_key=True),
    Column("action_id", String(64), ForeignKey("tutor_actions.action_id"), nullable=False),
    Column("student_id", String(64), ForeignKey("student_profiles.student_id"), nullable=False),
    Column("cycle_id", String(64), ForeignKey("tutoring_cycles.cycle_id"), nullable=False),
    Column("assistance_level", Integer, nullable=False),
    Column("issued_at", Text, nullable=False),
)

mastery_evidence = Table(
    "mastery_evidence",
    metadata,
    Column("evidence_id", String(64), primary_key=True),
    Column("student_id", String(64), ForeignKey("student_profiles.student_id"), nullable=False),
    # First-class replay facts.  Before migration 006 these were reconstructed
    # through assessment/log/problem joins, making evidence replay needlessly
    # dependent on adjacent tables.
    Column("attempt_id", String(64), nullable=False),
    Column("skill_id", String(64), nullable=False),
    Column("attempt_assessment_log_id", String(64), ForeignKey("attempt_assessments.verification_log_id"), nullable=False),
    Column("problem_grounding_id", String(64), nullable=True),
    Column("target_mapping_id", String(64), nullable=True),
    Column("correctness", String(16), nullable=False),
    Column("score", Float, nullable=False),
    Column("difficulty", Integer, nullable=False, default=0),
    Column("effective_assistance_level", Integer, nullable=False, default=0),
    Column("evidence_version", Text, nullable=False),
    # Idempotency: the same attempt can never insert evidence twice.
    Column("idempotency_key", String(128), nullable=False, unique=True),
    Column("created_at", Text, nullable=False),
    ForeignKeyConstraint(
        ["attempt_id", "student_id"],
        ["attempts.attempt_id", "attempts.student_id"],
        name="fk_evidence_attempt_owner",
    ),
    # Append-only: no UPDATE path.
)

student_state_projections = Table(
    "student_state_projections",
    metadata,
    Column("student_id", String(64), ForeignKey("student_profiles.student_id"), primary_key=True),
    Column("curriculum_version_id", String(64), nullable=True),
    Column("estimator_version", Text, nullable=False),
    Column("projection_version", Integer, nullable=False, default=0),
    Column("concept_mastery", JSON, nullable=False),
    Column("skill_mastery", JSON, nullable=False),
    Column("active_misconceptions", JSON, nullable=False),
    Column("updated_at", Text, nullable=False),
    # Updates use compare-and-set on projection_version (see repositories).
)

misconception_observations = Table(
    "misconception_observations",
    metadata,
    Column("observation_id", String(64), primary_key=True),
    Column("student_id", String(64), ForeignKey("student_profiles.student_id"), nullable=False),
    Column("attempt_id", String(64), ForeignKey("attempts.attempt_id"), nullable=False),
    Column("rule_id", String(64), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("detail", JSON, nullable=False),
    Column("created_at", Text, nullable=False),
    # One observation per (attempt, rule): the same attempt can never emit
    # the same rule twice — append-only, no UPDATE path.
    UniqueConstraint("attempt_id", "rule_id", name="uq_misconception_attempt_rule"),
)

domain_outbox = Table(
    "domain_outbox",
    metadata,
    Column("outbox_id", String(64), primary_key=True),
    Column("aggregate_type", String(48), nullable=False),
    Column("aggregate_id", String(64), nullable=False),
    Column("aggregate_version", Integer, nullable=False),
    Column("event_sequence", Integer, nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("audience", String(16), nullable=False, default="student"),
    Column("payload", JSON, nullable=False),
    Column("created_at", Text, nullable=False),
    # Relay resumes from here without re-publishing duplicates.
    UniqueConstraint(
        "aggregate_type", "aggregate_id", "aggregate_version", "event_sequence",
        name="uq_outbox_event",
    ),
)

# ------------------------------------------------- curriculum catalog (005)

curriculum_versions = Table(
    "curriculum_versions",
    metadata,
    Column("version_id", String(64), primary_key=True),
    Column("code", String(64), nullable=False, unique=True),
    Column("name", String(128), nullable=False),
    Column("status", String(16), nullable=False, default="draft"),
    Column("node_count", Integer, nullable=False, default=0),
    Column("edge_count", Integer, nullable=False, default=0),
    Column("released_at", Text, nullable=True),
    Column("created_at", Text, nullable=False),
)

curriculum_nodes = Table(
    "curriculum_nodes",
    metadata,
    Column("node_id", String(64), primary_key=True),
    Column("version_id", String(64), ForeignKey("curriculum_versions.version_id"), nullable=False),
    Column("code", String(64), nullable=False),
    Column("kind", String(16), nullable=False),  # chapter | concept | skill
    Column("title", String(128), nullable=False),
    Column("stage", String(16), nullable=True),  # primary | middle | high
    Column("grade", Integer, nullable=True),
    # One node code per version (the code IS the stable curriculum identity).
    UniqueConstraint("version_id", "code", name="uq_curriculum_node_version_code"),
)

curriculum_edges = Table(
    "curriculum_edges",
    metadata,
    Column("edge_id", String(64), primary_key=True),
    Column("version_id", String(64), ForeignKey("curriculum_versions.version_id"), nullable=False),
    Column("from_node_id", String(64), ForeignKey("curriculum_nodes.node_id"), nullable=False),
    Column("to_node_id", String(64), ForeignKey("curriculum_nodes.node_id"), nullable=False),
    Column("kind", String(24), nullable=False),  # PREREQUISITE_OF | PART_OF | RELATED_TO
)

# Outbox relay ledger (005): the relay is idempotent and restart-safe by
# recording every dispatch here in the SAME transaction scope as its sink.
# The unique key mirrors domain_outbox's own (aggregate_type, aggregate_id,
# aggregate_version, event_sequence) — a replayed event can never be
# dispatched twice, and an interrupted run resumes from its watermark.
outbox_dispatch_ledger = Table(
    "outbox_dispatch_ledger",
    metadata,
    Column("outbox_id", String(64), ForeignKey("domain_outbox.outbox_id"), primary_key=True),
    Column("aggregate_type", String(48), nullable=False),
    Column("aggregate_id", String(64), nullable=False),
    Column("aggregate_version", Integer, nullable=False),
    Column("event_sequence", Integer, nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("sink_id", String(64), nullable=False),
    Column("dispatched_at", Text, nullable=False),
    Column("attempts", Integer, nullable=False, default=1),
    Column("last_error", Text, nullable=True),
    UniqueConstraint(
        "aggregate_type", "aggregate_id", "aggregate_version", "event_sequence",
        name="uq_outbox_dispatch_event",
    ),
)


# ------------------------------------------------- practice catalog (004)

exercises = Table(
    "exercises",
    metadata,
    Column("exercise_id", String(64), primary_key=True),
    Column("problem_id", String(64), ForeignKey("math_problems.problem_id"), nullable=False),
    Column("problem_grounding_id", String(64), nullable=False),
    Column("display_latex", Text, nullable=False),
    Column("difficulty", Integer, nullable=False),
    Column("target_mapping_ids", JSON, nullable=False),
    Column("license_ref", Text, nullable=False, default=""),
    # Phase 5 provenance: source_type is a CLAIM, never a trust grant.
    Column("source_type", String(16), nullable=False),
    Column("content_hash", String(64), nullable=False, unique=True),
    Column("problem_statement", Text, nullable=False, default=""),
    Column("created_at", Text, nullable=False),
)

exercise_releases = Table(
    "exercise_releases",
    metadata,
    Column("release_id", String(64), primary_key=True),
    Column("exercise_id", String(64), ForeignKey("exercises.exercise_id"), nullable=False),
    Column("problem_hash", String(64), nullable=False),
    Column("solution_hash", String(64), nullable=False),
    Column("verification_policy_hash", String(64), nullable=False),
    Column("verifier_hash", String(64), nullable=False),
    Column("solution_candidate_hash", String(64), nullable=False),
    Column("license_hash", String(64), nullable=False),
    Column("provenance_hash", String(64), nullable=False),
    # Exact-snapshot binding: judging binds THIS candidate + THIS log.
    Column("solution_candidate_id", String(64), nullable=True),
    Column("verification_log_id", String(64), nullable=True),
    Column("status", String(16), nullable=False, default="draft"),
    Column("released_at", Text, nullable=True),
    # Append-only by convention: status flips (released→revoked/superseded)
    # are the ONLY UPDATE path; hashes never change in place.
)

practice_offers = Table(
    "practice_offers",
    metadata,
    Column("offer_id", String(64), primary_key=True),
    Column("student_id", String(64), ForeignKey("student_profiles.student_id"), nullable=False),
    Column("parent_cycle_id", String(64), ForeignKey("tutoring_cycles.cycle_id"), nullable=False),
    Column("exercise_release_id", String(64), ForeignKey("exercise_releases.release_id"), nullable=False),
    Column("target_mapping_ids", JSON, nullable=False),
    Column("stage_policy_version", Text, nullable=False, default="mt-stage-v0"),
    Column("status", String(16), nullable=False, default="ACTIVE"),
    Column("offered_at", Text, nullable=False),
    Column("expires_at", Text, nullable=False),
    Column("consumed_at", Text, nullable=True),
    # Owner-scoped: every query carries student_id (client never supplies it).
)

# ------------------------------------------------- personal memory KG (003)

personal_memory_nodes = Table(
    "personal_memory_nodes",
    metadata,
    Column("memory_id", String(64), primary_key=True),
    Column("student_id", String(64), ForeignKey("student_profiles.student_id"), nullable=False),
    Column("memory_type", String(48), nullable=False),
    Column("subject", String(128), nullable=False),
    Column("predicate", String(128), nullable=False),
    Column("object_json", JSON, nullable=False),
    Column("source_type", String(24), nullable=False),
    Column("confidence", Float, nullable=False, default=0.5),
    Column("retrieval_enabled", Integer, nullable=False, default=1),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Column("deleted_at", Text, nullable=True),
    # Owner-scoped: every query carries student_id (client never supplies it).
)

personal_memory_edges = Table(
    "personal_memory_edges",
    metadata,
    Column("edge_id", String(64), primary_key=True),
    Column("student_id", String(64), ForeignKey("student_profiles.student_id"), nullable=False),
    Column("source_node_id", String(64), ForeignKey("personal_memory_nodes.memory_id"), nullable=False),
    Column("relation", String(64), nullable=False),
    Column("target_node_id", String(64), ForeignKey("personal_memory_nodes.memory_id"), nullable=False),
    Column("confidence", Float, nullable=False, default=0.5),
    Column("created_at", Text, nullable=False),
    Column("deleted_at", Text, nullable=True),
)

# ------------------------------------------------- user documents (003)

user_documents = Table(
    "user_documents",
    metadata,
    Column("document_id", String(64), primary_key=True),
    Column("student_id", String(64), ForeignKey("student_profiles.student_id"), nullable=False),
    Column("filename", String(255), nullable=False),
    Column("mime_type", String(128), nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("storage_ref", Text, nullable=False),
    Column("status", String(16), nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("parser_version", Text, nullable=False, default=""),
    Column("retrieval_enabled", Integer, nullable=False, default=1),
    Column("parse_error", Text, nullable=False, default=""),
    Column("created_at", Text, nullable=False),
    Column("deleted_at", Text, nullable=True),
    # Duplicate-hash semantics: one student imports the same bytes once.
    UniqueConstraint("student_id", "content_hash", name="uq_document_owner_hash"),
)

document_chunks = Table(
    "document_chunks",
    metadata,
    Column("chunk_id", String(64), primary_key=True),
    Column("document_id", String(64), ForeignKey("user_documents.document_id"), nullable=False),
    Column("student_id", String(64), ForeignKey("student_profiles.student_id"), nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("page", Integer, nullable=True),
    Column("section", Text, nullable=False, default=""),
    Column("text", Text, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("metadata_json", JSON, nullable=False),
    Column("chunker_version", Text, nullable=False),
    UniqueConstraint("document_id", "sequence", name="uq_chunk_document_seq"),
)

# Embedding vectors are a DERIVED projection of chunks; they live in the
# same SQLite file (JSON column). The vector backend choice (sqlite-vec or
# an external file store) is a Phase 6 retrieval-infrastructure decision —
# the repository Protocol hides it from upper layers either way.
document_chunk_vectors = Table(
    "document_chunk_vectors",
    metadata,
    Column("chunk_id", String(64), primary_key=True),
    Column("document_id", String(64), ForeignKey("user_documents.document_id"), nullable=False),
    Column("student_id", String(64), ForeignKey("student_profiles.student_id"), nullable=False),
    Column("embedding_backend_id", String(64), nullable=False),
    Column("embedding_model_id", String(128), nullable=False),
    Column("embedding_model_version", String(64), nullable=False),
    Column("embedding_dimension", Integer, nullable=False),
    Column("vector", JSON, nullable=False),
    Column("created_at", Text, nullable=False),
)

# Index lifecycle: one row per (student, document) — the CURRENT build.
# Any signature change (embedding backend/model/dimension, chunker or
# parser version) marks the row stale → the index manager rebuilds; the
# original file is NEVER re-imported.
document_index_builds = Table(
    "document_index_builds",
    metadata,
    Column("student_id", String(64), ForeignKey("student_profiles.student_id"), primary_key=True),
    Column("document_id", String(64), ForeignKey("user_documents.document_id"), primary_key=True),
    Column("index_version", Integer, nullable=False),
    Column("embedding_backend_id", String(64), nullable=False),
    Column("embedding_model_id", String(128), nullable=False),
    Column("embedding_model_version", String(64), nullable=False),
    Column("embedding_dimension", Integer, nullable=False),
    Column("chunker_version", Text, nullable=False),
    Column("parser_version", Text, nullable=False),
    Column("built_at", Text, nullable=False),
)


__all__ = [
    "assistance_issuances",
    "attempt_assessments",
    "attempt_submissions",
    "attempts",
    "curriculum_edges",
    "curriculum_nodes",
    "curriculum_versions",
    "cycle_transitions",
    "document_chunk_vectors",
    "document_chunks",
    "document_index_builds",
    "domain_outbox",
    "exercise_releases",
    "exercises",
    "learning_sessions",
    "mastery_evidence",
    "math_problems",
    "metadata",
    "misconception_observations",
    "outbox_dispatch_ledger",
    "personal_memory_edges",
    "personal_memory_nodes",
    "practice_offers",
    "problem_submissions",
    "solution_candidates",
    "student_profiles",
    "student_state_projections",
    "tutor_actions",
    "tutoring_cycles",
    "user_documents",
    "users",
    "verification_logs",
]
