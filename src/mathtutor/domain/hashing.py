"""Content hashing and canonical JSON for the math_tutor domain.

Hashes are always *server-owned*: clients never write hash fields. Every
immutable record (canonical problem, solution candidate, verification
decision, attestation) is bound to the exact bytes it was issued against.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel


def to_json_safe(value: Any) -> Any:
    """Recursively convert domain values into JSON-serializable primitives."""
    if value is None or isinstance(value, (bool, int, str, float)):
        return value
    if isinstance(value, (UUID, Enum)):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {str(k): to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(v) for v in value]
    if isinstance(value, BaseModel):
        return to_json_safe(value.model_dump())
    raise TypeError(f"unsupported payload type: {type(value)!r}")


def content_hash(payload: dict[str, Any]) -> str:
    """SHA-256 over the canonical JSON encoding of ``payload``.

    ``sort_keys`` makes the digest independent of dict insertion order, so
    re-serializing the same logical payload always yields the same hash.
    """
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            to_json_safe(payload),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return digest.hexdigest()
