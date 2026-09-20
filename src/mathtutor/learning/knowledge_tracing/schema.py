"""Dedicated additive tables; migrations import this metadata explicitly."""
from sqlalchemy import JSON, Column, Integer, MetaData, String, Table, UniqueConstraint

metadata = MetaData()
initial_assessments = Table(
    "initial_assessments", metadata,
    Column("student_id", String(64), primary_key=True),
    Column("payload", JSON, nullable=False),
)
learning_generations = Table(
    "learning_generations", metadata,
    Column("student_id", String(64), primary_key=True),
    Column("generation", Integer, nullable=False, default=0),
)
practice_feedback = Table(
    "practice_feedback", metadata,
    Column("student_id", String(64), primary_key=True),
    Column("offer_id", String(64), primary_key=True),
    Column("kind", String(24), nullable=False),
    Column("created_at", String(64), nullable=False),
)
learning_events = Table(
    "learning_events", metadata,
    Column("student_id", String(64), primary_key=True),
    Column("event_id", String(160), primary_key=True),
    Column("event_seq", Integer, nullable=False),
    Column("event_type", String(48), nullable=False),
    Column("cycle_id", String(64), nullable=False),
    Column("payload", JSON, nullable=False),
    UniqueConstraint("student_id", "event_seq", name="uq_learning_event_student_seq"),
)
student_state_snapshots = Table(
    "student_state_snapshots", metadata,
    Column("student_id", String(64), primary_key=True),
    Column("last_event_seq", Integer, nullable=False),
    Column("model_version", String(128), nullable=False),
    Column("feature_schema_version", String(64), nullable=False),
    Column("graph_version", String(64), nullable=False),
    Column("payload", JSON, nullable=False),
)
learning_predictions = Table(
    "learning_predictions", metadata,
    Column("student_id", String(64), primary_key=True),
    Column("prediction_id", String(160), primary_key=True),
    Column("history_cutoff_seq", Integer, nullable=False),
    Column("payload", JSON, nullable=False),
)
