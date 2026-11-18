from sqlalchemy import JSON, Column, Float, Integer, MetaData, String, Table

metadata = MetaData()
recommendations = Table(
    "knowledge_recommendations", metadata,
    Column("student_id", String, primary_key=True),
    Column("generation", Integer, nullable=False),
    Column("enabled", Integer, nullable=False),
    Column("goal", String, nullable=False),
    Column("cache_key", String, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("updated_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
    Column("status", String, nullable=False),
    Column("lease_token", String, nullable=False),
    Column("lease_key", String, nullable=False),
    Column("lease_until", Float, nullable=False),
    Column("budget_day", String, nullable=False),
    Column("budget_calls", Integer, nullable=False),
)
