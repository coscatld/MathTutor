"""OS credential store adapter for :class:`SecretStore` (desktop product).

Backing stores (never a plain config file, never the business DB):

- macOS: the Keychain via the built-in ``security`` CLI (``service`` =
  ``com.mathtutor.product``). The secret is piped to the subprocess over
  stdin (never in ``argv``, so it does not leak into ``ps``); macOS
  ``security add-generic-password`` prompts twice, so the value is written
  twice.
- Linux: freedesktop Secret Service via ``secret-tool`` when available
  (value also via stdin).
- Windows: the Credential Manager via ``advapi32``
  (``CredWriteW``/``CredReadW``/``CredDeleteW``, ``CRED_TYPE_GENERIC``,
  target = ``f"{service}/{key}"``). The secret exists ONLY as the in-memory
  ``CREDENTIALW`` blob passed to ``CredWriteW`` — never in ``argv``, a
  plain file, logs or error messages. UNTESTED on a real Windows host (no
  Windows machine available); the adapter follows the documented
  CREDENTIALW ABI and ERROR_NOT_FOUND (1168) semantics and is exercised
  through an injectable fake backend on every other platform.

Fail-closed rules:

- any unexpected subprocess / API failure raises
  :class:`KeychainSecretStoreError` (never a silent fallback);
- ``get`` returns ``None`` ONLY for the documented not-found results
  (``security`` → 44, ``secret-tool`` → 1, Credential Manager →
  ERROR_NOT_FOUND 1168) — anything else raises;
- availability is probed explicitly (:meth:`KeychainSecretStore.available`);
  an unavailable store reports itself as such instead of scanning or
  stubbing.

Both the subprocess runner (macOS/Linux) and the Win32 backend (Windows)
are injectable so tests use fakes and never touch a real credential store.
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
from typing import Awaitable, Callable, Protocol

from mathtutor.infrastructure.secret_store import SecretStore

DEFAULT_SERVICE_NAME = "com.mathtutor.product"
DEFAULT_TIMEOUT_SECONDS = 10.0

# ``security`` exits 44 when the item does not exist (both find and delete).
_SECURITY_NOT_FOUND_EXIT = 44
# ``secret-tool lookup`` exits 1 when the attribute set has no secret.
_SECRET_TOOL_NOT_FOUND_EXIT = 1

# Credential Manager constants (Windows, advapi32).
_WIN32_CRED_TYPE_GENERIC = 1
_WIN32_CRED_PERSIST_LOCAL_MACHINE = 2
# ERROR_NOT_FOUND: no credential matches the target name.
_WIN32_ERROR_NOT_FOUND = 1168


class KeychainSecretStoreError(RuntimeError):
    """The OS credential store refused an operation (fail closed)."""


class KeychainUnsupportedError(KeychainSecretStoreError):
    """No OS credential store is available on this platform / host.

    Raised instead of silently degrading: callers must surface this as an
    explicit "unsupported" state, never fall back to insecure storage.
    """


class KeychainUnavailableError(KeychainSecretStoreError):
    """The credential-store binary exists but could not be executed."""


class SubprocessRunner(Protocol):
    """Async ``(argv, stdin_bytes) -> (exit_code, stdout, stderr)``."""

    async def run(
        self, argv: list[str], *, stdin: bytes | None = None
    ) -> tuple[int, str, str]: ...


async def _default_runner(
    argv: list[str], *, stdin: bytes | None = None
) -> tuple[int, str, str]:
    """Production runner: asyncio subprocess with the secret over stdin."""
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        process.communicate(input=stdin), timeout=DEFAULT_TIMEOUT_SECONDS
    )
    return process.returncode if process.returncode is not None else -1, (
        stdout.decode("utf-8", errors="replace")
    ), stderr.decode("utf-8", errors="replace")


def _which(command: str) -> bool:
    try:
        return shutil.which(command) is not None
    except Exception:  # pragma: no cover - defensive
        return False


class Win32CredBackend(Protocol):
    """Async Credential Manager adapter (Windows, advapi32).

    ``target`` is ``f"{service}/{key}"`` (a CRED_TYPE_GENERIC target name);
    ``blob`` is the raw byte payload of the credential (UTF-16-LE encoded
    secret value) written verbatim into ``CREDENTIALW.CredentialBlob``.

    Contract:

    - ``cred_write`` overwrites any existing credential with the same
      target; API failure raises :class:`KeychainSecretStoreError`;
    - ``cred_read`` returns the stored bytes, or ``None`` when no
      credential matches the target (ERROR_NOT_FOUND / 1168);
    - ``cred_delete`` deletes the credential; a missing credential
      (1168) counts as success.

    The secret never appears in an error message, a log line or a file —
    only in the in-memory blob handed to ``CredWriteW``.
    """

    async def cred_write(self, target: str, blob: bytes) -> None: ...

    async def cred_read(self, target: str) -> bytes | None: ...

    async def cred_delete(self, target: str) -> None: ...


def _win32_not_found_or_raise(error_code: int, operation: str) -> bool:
    """Map a Credential Manager API failure onto fail-closed semantics.

    ERROR_NOT_FOUND (1168) is the documented "no such credential" result —
    callers translate it into ``get → None`` / ``delete → success``. Any
    other code raises :class:`KeychainSecretStoreError`; the message names
    only the operation and the numeric error code, NEVER credential
    material.
    """
    if error_code == _WIN32_ERROR_NOT_FOUND:
        return True
    raise KeychainSecretStoreError(f"{operation} failed (win32 error {error_code})")


def _win32_api_available() -> bool:
    """True when advapi32 (Credential Manager) can be loaded.

    Pure probe — never writes, never reads credentials. On non-Windows
    hosts ``ctypes.WinDLL`` does not exist, so this is always False.
    """
    try:
        import ctypes

        ctypes.WinDLL("advapi32")
        return True
    except Exception:  # pragma: no cover - non-Windows hosts
        return False


def _default_win32_backend() -> Win32CredBackend:
    """Production Credential Manager adapter (advapi32 via ctypes).

    Windows-only: guarded by ``platform.system()`` in the store, so this
    factory is never invoked on other platforms. **UNTESTED on a real
    Windows host** — no Windows machine is available in this project; the
    struct layout follows the documented CREDENTIALW ABI and the
    ERROR_NOT_FOUND (1168) semantics are covered by the pure helper above
    and the fake-backend tests.

    The secret rides only the in-memory ``CREDENTIALW.CredentialBlob``
    pointer passed to ``CredWriteW`` (DPAPI-encrypted by the OS at rest);
    it is never placed in ``argv``, an environment variable, a log line or
    a plain file.
    """
    import ctypes
    from ctypes import wintypes

    class _FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    class _CREDENTIALW(ctypes.Structure):
        # https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", _FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(wintypes.BYTE)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    advapi32.CredWriteW.restype = wintypes.BOOL
    advapi32.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    advapi32.CredDeleteW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    advapi32.CredFree.restype = None

    class _Backend:
        async def cred_write(self, target: str, blob: bytes) -> None:
            blob_buffer = ctypes.create_string_buffer(blob, len(blob))
            credential = _CREDENTIALW()
            credential.Type = _WIN32_CRED_TYPE_GENERIC
            credential.TargetName = target
            credential.CredentialBlobSize = len(blob)
            credential.CredentialBlob = ctypes.cast(
                blob_buffer, ctypes.POINTER(wintypes.BYTE)
            )
            credential.Persist = _WIN32_CRED_PERSIST_LOCAL_MACHINE
            if not advapi32.CredWriteW(ctypes.byref(credential), 0):
                raise KeychainSecretStoreError(
                    f"CredWriteW failed (win32 error {ctypes.get_last_error()})"
                )

        async def cred_read(self, target: str) -> bytes | None:
            pointer = ctypes.c_void_p()
            if not advapi32.CredReadW(target, _WIN32_CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
                # Raises unless the code is ERROR_NOT_FOUND (1168).
                _win32_not_found_or_raise(ctypes.get_last_error(), "CredReadW")
                return None
            try:
                credential = ctypes.cast(pointer, ctypes.POINTER(_CREDENTIALW)).contents
                return bytes(ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize))
            finally:
                advapi32.CredFree(pointer)

        async def cred_delete(self, target: str) -> None:
            if not advapi32.CredDeleteW(target, _WIN32_CRED_TYPE_GENERIC, 0):
                _win32_not_found_or_raise(ctypes.get_last_error(), "CredDeleteW")
                return
            return None

    return _Backend()


class KeychainSecretStore:
    """SecretStore backed by the OS credential store on supported desktops."""

    store_id = "keychain"

    def __init__(
        self,
        *,
        service: str = DEFAULT_SERVICE_NAME,
        runner: Callable[..., Awaitable[tuple[int, str, str]]] | None = None,
        win32_backend: Win32CredBackend | None = None,
    ) -> None:
        self._service = service
        self._runner = runner if runner is not None else _default_runner
        self._win32_backend = win32_backend

    # ------------------------------------------------------------ platform

    @classmethod
    def available(cls) -> bool:
        """True when an OS credential store can back this store.

        Pure probe — never attempts to write. macOS requires the ``security``
        CLI; Linux requires ``secret-tool``; Windows requires a loadable
        advapi32 (Credential Manager). Anything else is unsupported.
        """
        system = platform.system()
        if system == "Darwin":
            return _which("security")
        if system == "Linux":
            return _which("secret-tool")
        if system == "Windows":
            return _win32_api_available()
        return False

    def _check_supported(self) -> None:
        system = platform.system()
        if system == "Windows":
            # Credential Manager adapter. Fail closed when advapi32 cannot
            # be probed: never fall back to insecure storage.
            if not _win32_api_available():
                raise KeychainUnavailableError(
                    "Windows Credential Manager (advapi32) unavailable — "
                    "refusing to fall back to insecure storage"
                )
            return
        if not self.available():
            if system not in {"Darwin", "Linux"}:
                raise KeychainUnsupportedError(
                    f"no OS credential store adapter for platform {system!r}"
                )
            raise KeychainUnavailableError(
                f"credential store CLI missing on {system} "
                "(security/secret-tool) — credential store unavailable"
            )

    # ------------------------------------------------------------ commands

    def _put_argv(self, key: str) -> list[str]:
        return [
            "security",
            "add-generic-password",
            "-U",
            "-s",
            self._service,
            "-a",
            key,
            "-w",
        ]

    def _find_argv(self, key: str) -> list[str]:
        return ["security", "find-generic-password", "-s", self._service, "-a", key, "-w"]

    def _delete_argv(self, key: str) -> list[str]:
        return ["security", "delete-generic-password", "-s", self._service, "-a", key]

    async def _run_linux(
        self, argv: list[str], *, stdin: bytes | None = None
    ) -> tuple[int, str, str]:
        if not _which("secret-tool"):
            raise KeychainUnavailableError(
                "secret-tool (freedesktop Secret Service) not found on Linux"
            )
        return await self._runner(argv, stdin=stdin)

    # ------------------------------------------------------------- SecretStore

    def _win32_target(self, key: str) -> str:
        """Credential Manager target name for a key (CRED_TYPE_GENERIC).

        The target contains only the service name and the key — never the
        secret value itself.
        """
        return f"{self._service}/{key}"

    def _win32(self) -> Win32CredBackend:
        backend = self._win32_backend
        return backend if backend is not None else _default_win32_backend()

    async def put(self, key: str, value: str) -> None:
        self._check_supported()
        if platform.system() == "Windows":
            # The value rides ONLY the in-memory CREDENTIALW blob; the
            # UTF-16-LE payload is the conventional generic-credential
            # encoding readable by the Credential Manager UI.
            await self._win32().cred_write(
                self._win32_target(key), value.encode("utf-16-le")
            )
            return
        if platform.system() == "Linux":
            argv = [
                "secret-tool",
                "store",
                "--label=MathTutor API key",
                "service",
                self._service,
                "key",
                key,
            ]
            stdin = f"{value}\n".encode("utf-8")
            exit_code, _stdout, stderr = await self._run_linux(argv, stdin=stdin)
            if exit_code != 0:
                raise KeychainSecretStoreError(
                    f"secret-tool store failed (exit {exit_code}): {stderr.strip()}"
                )
            return
        # macOS: ``security add-generic-password -w`` prompts for the value
        # twice when no argument is given; both reads come from stdin. The
        # secret therefore NEVER appears in the process argv.
        stdin = f"{value}\n{value}\n".encode("utf-8")
        exit_code, _stdout, stderr = await self._runner(self._put_argv(key), stdin=stdin)
        if exit_code != 0:
            raise KeychainSecretStoreError(
                f"security add-generic-password failed (exit {exit_code}): "
                f"{stderr.strip()}"
            )

    async def get(self, key: str) -> str | None:
        self._check_supported()
        if platform.system() == "Windows":
            blob = await self._win32().cred_read(self._win32_target(key))
            if blob is None:  # ERROR_NOT_FOUND (1168) → no credential
                return None
            return blob.decode("utf-16-le")
        if platform.system() == "Linux":
            argv = ["secret-tool", "lookup", "service", self._service, "key", key]
            exit_code, stdout, stderr = await self._run_linux(argv)
            if exit_code == _SECRET_TOOL_NOT_FOUND_EXIT:
                return None
            if exit_code != 0:
                raise KeychainSecretStoreError(
                    f"secret-tool lookup failed (exit {exit_code}): {stderr.strip()}"
                )
            value = stdout.rstrip("\n")
            return value if value else None
        exit_code, stdout, stderr = await self._runner(self._find_argv(key))
        if exit_code == _SECURITY_NOT_FOUND_EXIT:
            return None
        if exit_code != 0:
            raise KeychainSecretStoreError(
                f"security find-generic-password failed (exit {exit_code}): "
                f"{stderr.strip()}"
            )
        value = stdout.rstrip("\n")
        return value if value else None

    async def delete(self, key: str) -> None:
        self._check_supported()
        if platform.system() == "Windows":
            # ERROR_NOT_FOUND (1168) counts as success: deleting an
            # already-gone credential is a no-op.
            await self._win32().cred_delete(self._win32_target(key))
            return
        if platform.system() == "Linux":
            argv = ["secret-tool", "clear", "service", self._service, "key", key]
            exit_code, _stdout, stderr = await self._run_linux(argv)
            if exit_code not in (0, _SECRET_TOOL_NOT_FOUND_EXIT):
                raise KeychainSecretStoreError(
                    f"secret-tool clear failed (exit {exit_code}): {stderr.strip()}"
                )
            return
        exit_code, _stdout, stderr = await self._runner(self._delete_argv(key))
        if exit_code not in (0, _SECURITY_NOT_FOUND_EXIT):
            raise KeychainSecretStoreError(
                f"security delete-generic-password failed (exit {exit_code}): "
                f"{stderr.strip()}"
            )


__all__ = [
    "DEFAULT_SERVICE_NAME",
    "KeychainSecretStore",
    "KeychainSecretStoreError",
    "KeychainUnavailableError",
    "KeychainUnsupportedError",
    "SubprocessRunner",
    "Win32CredBackend",
    "_default_runner",
    "_default_win32_backend",
    "_win32_api_available",
    "_win32_not_found_or_raise",
]
