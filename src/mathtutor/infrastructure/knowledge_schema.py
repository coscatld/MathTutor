"""020: owner-scoped knowledge facts and regenerable review projections."""
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, Text

metadata = MetaData()

spaces = Table("knowledge_spaces", metadata,
    Column("student_id", String, primary_key=True), Column("space_id", String, primary_key=True),
    Column("kind", String, nullable=False), Column("name", Text, nullable=False),
    Column("conversation_id", String, nullable=False, default=""),
    Column("enabled", Integer, nullable=False, default=1), Column("deleted_at", Text),
    Column("created_at", Text, nullable=False))
members = Table("knowledge_members", metadata,
    Column("student_id", String, primary_key=True), Column("space_id", String, primary_key=True),
    Column("document_id", String, primary_key=True))
bindings = Table("knowledge_bindings", metadata,
    Column("student_id", String, primary_key=True), Column("conversation_id", String, primary_key=True),
    Column("payload", JSON, nullable=False))
versions = Table("knowledge_versions", metadata,
    Column("student_id", String, primary_key=True), Column("document_id", String, primary_key=True),
    Column("version", Integer, primary_key=True), Column("body", Text, nullable=False),
    Column("body_hash", String, nullable=False), Column("title", Text, nullable=False),
    Column("tags", JSON, nullable=False), Column("links", JSON, nullable=False),
    Column("provenance", JSON, nullable=False), Column("created_at", Text, nullable=False))
generations = Table("knowledge_generations", metadata,
    Column("student_id", String, primary_key=True), Column("generation", Integer, nullable=False))
operations = Table("knowledge_operations", metadata,
    Column("student_id", String, primary_key=True), Column("operation_id", String, primary_key=True),
    Column("fingerprint", String, nullable=False), Column("payload", JSON, nullable=False),
    Column("generation", Integer, nullable=False))
# Citation receipts: proof that a specific immutable range was legitimately
# surfaced to this owner in this conversation.
#
# A receipt grants NO new authority. It records that authority was already
# exercised, and lets a historical citation be RE-VERIFIED after active
# retrieval permission has changed (document disabled). It never widens a
# range: validation requires the requested tuple to equal the receipt tuple
# exactly.
#
# Deletion is physical for this product, and the requirements settle the
# conflict explicitly: privacy deletion overrides historical citation
# availability. `forget_document` therefore removes receipts too, and
# validation additionally re-reads the immutable version — a receipt whose
# version row is gone fails closed rather than resurrecting the content.
receipts = Table("knowledge_citation_receipts", metadata,
    Column("student_id", String, primary_key=True), Column("receipt_id", String, primary_key=True),
    Column("conversation_id", String, nullable=False), Column("document_id", String, nullable=False),
    Column("document_version", Integer, nullable=False), Column("start", Integer, nullable=False),
    Column("end", Integer, nullable=False), Column("body_hash", String, nullable=False),
    Column("source_id", String, nullable=False), Column("generation_at_issue", Integer, nullable=False),
    Column("issued_at", Text, nullable=False))
drafts = Table("knowledge_drafts", metadata,
    Column("student_id", String, primary_key=True), Column("draft_id", String, primary_key=True),
    Column("generation", Integer, nullable=False), Column("payload", JSON, nullable=False))
reviews = Table("stage_reviews", metadata,
    Column("student_id", String, primary_key=True), Column("payload", JSON, nullable=False),
    Column("generation", Integer, nullable=False), Column("last_event_seq", Integer, nullable=False),
    Column("evidence_key", String, nullable=False))
preferences = Table("stage_preferences", metadata,
    Column("student_id", String, primary_key=True), Column("payload", JSON, nullable=False))
