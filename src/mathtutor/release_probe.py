"""Safe, machine-readable RC probes executed by packaged smoke.

The Electron shell only launches this module.  Database/retrieval knowledge
stays in Python beside the product implementation, and output is deliberately
limited to release metadata and booleans (never document text or secrets).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any, Sequence

from mathtutor.application.document_ingestion import DocumentIndexManager
from mathtutor.infrastructure.db import create_db_engine
from mathtutor.infrastructure.embedding_runtime import EmbeddingRuntime
from mathtutor.repositories.sqlite_knowledge import SQLiteDocumentRepository
from mathtutor.security.scopes import DEV_STUDENT_ID


def migration_probe(db_path: Path) -> dict[str, Any]:
    from mathtutor.infrastructure import db_crypto
    connection = db_crypto.connect_db(db_path)
    try:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    finally:
        connection.close()
    return {"head": str(row[0]) if row else ""}


async def document_retrieval_probe(db_path: Path, query: str) -> dict[str, Any]:
    engine = create_db_engine(db_path)
    try:
        search = DocumentIndexManager(
            repository=SQLiteDocumentRepository(engine),
            embedding_runtime=EmbeddingRuntime(),
        )
        result = await search.search(DEV_STUDENT_ID, query=query, limit=5)
        return {"hit": bool(result.hits), "vector_used": result.vector_used}
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("migration", "document-retrieval"))
    parser.add_argument("db_path", type=Path)
    parser.add_argument("query", nargs="?", default="")
    args = parser.parse_args(argv)
    if args.operation == "migration":
        payload = migration_probe(args.db_path)
    else:
        if not args.query.strip():
            parser.error("document-retrieval requires a query")
        payload = asyncio.run(document_retrieval_probe(args.db_path, args.query))
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["document_retrieval_probe", "main", "migration_probe"]
