"""Public verification receipt projection from private continuation state.

The stored continuation context can contain prompts and raw drafts.  Only the
named public receipt may accompany the approved response body on the wire.
"""
from __future__ import annotations

import json


def parse_continuation_context(value: object) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def verification_notice_fields(context: object) -> dict[str, str]:
    notice = parse_continuation_context(context).get("verification_notice")
    if isinstance(notice, str) and notice.strip():
        return {"verification_notice": notice.strip()}
    return {}
