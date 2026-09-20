"""Request-local document whitelist for the active conversation.

Contract — read this before consuming :func:`current_document_scope`:

``None``    no scope was established for this task. The task did not run
            inside a conversation turn. This MUST be read as "no documents".
            Reading it as "all documents" silently crosses conversation
            boundaries, so every consumer fails closed on ``None``.
``()``      a scope was established and the conversation has no documents.
            Also "no documents", but distinguishable in provenance detail.

The two states are kept distinct on purpose: telemetry must be able to tell
"this path never set a scope" (a wiring bug) apart from "this conversation
genuinely has no documents" (normal).

Only :func:`mathtutor.api.math_tutor_ws` sets the scope in production, per
turn, before the controller runs.
"""

from contextvars import ContextVar, Token
from typing import Sequence
from uuid import UUID

_document_ids: ContextVar[tuple[UUID, ...] | None] = ContextVar("conversation_document_ids", default=None)


def set_document_scope(document_ids: Sequence[UUID]) -> Token:
    """Establish the active conversation's whitelist for the current task."""
    return _document_ids.set(tuple(document_ids))


def reset_document_scope(token: Token) -> None:
    _document_ids.reset(token)


def current_document_scope() -> tuple[UUID, ...] | None:
    """Return the whitelist, or ``None`` when no scope was established.

    ``None`` never means "unrestricted" — see the module contract.
    """
    return _document_ids.get()
