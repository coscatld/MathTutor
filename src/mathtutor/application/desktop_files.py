"""Desktop file picking contract — the ONLY entry for user documents.

Design contract (§14): documents enter the system EXCLUSIVELY through an
explicit user file pick. The business layer never scans the host disk
(no Desktop/Documents/Downloads traversal) and never accepts a raw path
as an import source — it receives a :class:`PickedFile` (bytes already
read by the picker) and only the ``original_path`` is kept for display
provenance. After import, storage is addressed by ``document_id`` under
MathTutor-controlled storage; the host path is never re-read.

Adapters:

- :class:`InMemoryPickedFilePicker` — deterministic dev/tests picker;
- :class:`NativeDesktopFilePicker` — the shipped desktop adapter. It NEVER
  scans the disk: it delegates the OS dialog to a *pick transport* and
  receives the picked bytes back. Production wires
  :class:`LoopbackElectronPickTransport` (asks the Electron shell over
  loopback — ``MATHTUTOR_ELECTRON_PICKER_URL``); tests inject a fake
  transport. When no transport is wired the picker raises
  :class:`PickTransportUnavailableError` instead of silently degrading or
  scanning directories.
"""

from __future__ import annotations

import base64
import inspect
import os
from typing import Awaitable, Callable, Protocol

import httpx
from pydantic import BaseModel, ConfigDict

# The Electron shell's native-picker listener URL (set by the shell when it
# spawns the Python service). Example: http://127.0.0.1:38291
PICKER_URL_ENV = "MATHTUTOR_ELECTRON_PICKER_URL"

# Timeout for asking the shell to show the dialog (local loopback).
PICKER_TIMEOUT_SECONDS = 60.0


class PickedFile(BaseModel):
    """One user-picked file: bytes + display metadata.

    ``original_path`` is provenance ONLY (shown in UI); ingestion never
    reads the host path again.
    """

    model_config = ConfigDict(frozen=True)

    filename: str
    mime_type: str = ""
    data: bytes = b""
    original_path: str = ""


class DesktopFilePicker(Protocol):
    """Native file-picker contract (async; None = user cancelled)."""

    async def pick_document_file(self, student_id: str) -> PickedFile | None: ...


class PickTransportUnavailableError(RuntimeError):
    """No native pick transport is wired/reachable.

    Raised instead of scanning the disk or inventing a file: the caller
    surfaces this as an explicit "native file picking unsupported" state.
    """


class PickTransport(Protocol):
    """Async OS-dialog transport: ``(student_id) -> PickedFile | None``.

    ``None`` means the user cancelled the dialog. Unavailable transports
    raise :class:`PickTransportUnavailableError`.
    """

    async def pick(self, student_id: str) -> PickedFile | None: ...


class InMemoryPickedFilePicker:
    """Queue-backed picker for dev/tests (deterministic, no OS dialog)."""

    def __init__(self) -> None:
        self._queue: list[PickedFile] = []

    def enqueue(self, picked: PickedFile) -> None:
        self._queue.append(picked)

    async def pick_document_file(self, student_id: str) -> PickedFile | None:
        if not self._queue:
            return None
        return self._queue.pop(0)


class NativeDesktopFilePicker:
    """Real ``DesktopFilePicker``: the OS dialog via an injected transport.

    The picker itself contains NO file-system code: it forwards the request
    to ``transport.pick(student_id)`` and returns the bytes the transport
    obtained from the native dialog. Explicit pick only — there is no code
    path that enumerates user directories (an invariant the test suite
    asserts statically).

    ``transport`` may be ``None`` (default): then every pick raises
    :class:`PickTransportUnavailableError` — explicit "unsupported", never
    a silent scan or an empty-file fallback.

    A transport is either an object exposing ``pick(student_id)`` or a plain
    async callable ``(student_id) -> PickedFile | None`` (the in-memory
    picker's ``pick_document_file`` binds directly).
    """

    def __init__(
        self, transport: PickTransport | Callable[..., Awaitable[PickedFile | None]] | None = None
    ) -> None:
        self._transport = transport

    async def pick_document_file(self, student_id: str) -> PickedFile | None:
        if self._transport is None:
            raise PickTransportUnavailableError(
                "native file picking is not available: no pick transport "
                "is wired (desktop shell not reachable)"
            )
        transport = self._transport
        if not hasattr(transport, "pick"):
            result = transport(student_id)  # type: ignore[misc]
            if inspect.isawaitable(result):
                return await result
            return result  # type: ignore[return-value]
        return await transport.pick(student_id)


class LoopbackElectronPickTransport:
    """Production transport: ask the Electron shell over loopback.

    The Electron main process runs a tiny localhost HTTP listener (started
    before it spawns the Python service) and passes its URL via the
    ``MATHTUTOR_ELECTRON_PICKER_URL`` environment variable. This transport
    POSTs a pick request to ``{url}/native-pick``; the shell shows the OS
    dialog and answers with the picked file bytes (base64) or
    ``{"cancelled": true}``.

    The file bytes travel ONLY from the shell to the local Python service
    over loopback — never through renderer JS, never persisted by the
    renderer. Unreachable shell → :class:`PickTransportUnavailableError`.
    """

    def __init__(
        self,
        picker_url: str | None = None,
        *,
        timeout_seconds: float = PICKER_TIMEOUT_SECONDS,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._picker_url = (
            (picker_url or os.environ.get(PICKER_URL_ENV) or "").strip().rstrip("/")
        )
        self._timeout = httpx.Timeout(timeout_seconds)
        self._http = http

    def available(self) -> bool:
        return bool(self._picker_url)

    async def pick(self, student_id: str) -> PickedFile | None:
        if not self._picker_url:
            raise PickTransportUnavailableError(
                f"no native picker URL ({PICKER_URL_ENV} unset) — native "
                "file picking unsupported"
            )
        try:
            async with self._http or httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._picker_url}/native-pick",
                    json={"student_id": student_id},
                )
        except httpx.HTTPError as error:
            raise PickTransportUnavailableError(
                f"native picker shell unreachable: {error}"
            ) from error
        if response.status_code != 200:
            raise PickTransportUnavailableError(
                f"native picker shell returned HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise PickTransportUnavailableError(
                "native picker shell returned malformed JSON"
            ) from error
        if payload.get("cancelled"):
            return None
        filename = str(payload.get("filename") or "")
        if not filename:
            raise PickTransportUnavailableError(
                "native picker shell returned no filename"
            )
        raw = str(payload.get("data_base64") or "")
        try:
            data = base64.b64decode(raw) if raw else b""
        except (ValueError, TypeError) as error:
            raise PickTransportUnavailableError(
                "native picker shell returned invalid file data"
            ) from error
        return PickedFile(
            filename=filename,
            mime_type=str(payload.get("mime_type") or ""),
            data=data,
            original_path=str(payload.get("original_path") or ""),
        )


def picker_url_from_env() -> str:
    """The shell picker URL from the environment ("" when unset)."""
    return (os.environ.get(PICKER_URL_ENV) or "").strip()


__all__ = [
    "DesktopFilePicker",
    "InMemoryPickedFilePicker",
    "LoopbackElectronPickTransport",
    "NativeDesktopFilePicker",
    "PickTransport",
    "PickTransportUnavailableError",
    "PickedFile",
    "picker_url_from_env",
]

