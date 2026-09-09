"""Request-local document whitelist for the active conversation."""

from contextvars import ContextVar, Token
from typing import Sequence
from uuid import UUID

_document_ids: ContextVar[tuple[UUID, ...] | None] = ContextVar("conversation_document_ids", default=None)


def set_document_scope(document_ids: Sequence[UUID]) -> Token:
    return _document_ids.set(tuple(document_ids))


def reset_document_scope(token: Token) -> None:
    _document_ids.reset(token)


def current_document_scope() -> tuple[UUID, ...] | None:
    return _document_ids.get()
