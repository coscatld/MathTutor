from sqlalchemy import JSON, Column, Integer, MetaData, String, Table, Text

metadata = MetaData()

inquiries = Table(
    "exploration_inquiries", metadata,
    Column("student_id", String, primary_key=True),
    Column("inquiry_id", String, primary_key=True),
    Column("revision", Integer, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("updated_at", Text, nullable=False),
)
generations = Table(
    "exploration_generations", metadata,
    Column("student_id", String, primary_key=True),
    Column("generation", Integer, nullable=False),
)
