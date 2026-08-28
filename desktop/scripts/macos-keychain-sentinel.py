#!/usr/bin/env python3
"""Real macOS Keychain release sentinel with fail-safe cleanup.

The value is generated inside this process.  It is never accepted from argv,
printed, logged, or written to a file.  This adapter deliberately imports the
production ``KeychainSecretStore`` so the packaged runner can prove the exact
bundled implementation performs put/read/delete without a plaintext fallback.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import platform
import secrets
import sys
import uuid

from mathtutor.infrastructure.keychain_secret_store import (
    DEFAULT_SERVICE_NAME,
    KeychainSecretStore,
)


async def _probe() -> tuple[dict[str, object], int]:
    result: dict[str, object] = {
        "schema_version": 1,
        "platform": platform.system(),
        "store": "macOS Keychain",
        "service": DEFAULT_SERVICE_NAME,
        "status": "FAIL",
        "packaged_store_import": True,
        "secret_transport": "stdin_only",
        "secret_in_argv": False,
        "plaintext_fallback": False,
        "cleanup_complete": False,
        "operations": {
            "available": False,
            "put": False,
            "read_match": False,
            "delete": False,
            "missing_after_delete": False,
            "finally_delete": False,
            "missing_after_finally": False,
        },
    }
    operations = result["operations"]
    assert isinstance(operations, dict)
    key = f"release-assurance.{uuid.uuid4().hex}"
    value = secrets.token_urlsafe(48)
    store = KeychainSecretStore()
    failure_type: str | None = None

    try:
        if platform.system() != "Darwin":
            raise RuntimeError("macOS Keychain sentinel requires Darwin")
        operations["available"] = store.available()
        if not operations["available"]:
            raise RuntimeError("macOS Keychain is unavailable")

        await store.put(key, value)
        operations["put"] = True
        observed = await store.get(key)
        operations["read_match"] = observed is not None and hmac.compare_digest(
            observed, value
        )
        if not operations["read_match"]:
            raise RuntimeError("Keychain roundtrip mismatch")

        await store.delete(key)
        operations["delete"] = True
        operations["missing_after_delete"] = await store.get(key) is None
        if not operations["missing_after_delete"]:
            raise RuntimeError("Keychain item remained after delete")
    except Exception as exc:  # result contains the class only, never stderr/value
        failure_type = type(exc).__name__
    finally:
        try:
            # Required second delete: cleanup is attempted even after any
            # put/read/delete/assertion failure.
            await store.delete(key)
            operations["finally_delete"] = True
            operations["missing_after_finally"] = await store.get(key) is None
        except Exception as cleanup_exc:
            failure_type = failure_type or type(cleanup_exc).__name__

    result["cleanup_complete"] = bool(
        operations["finally_delete"] and operations["missing_after_finally"]
    )
    success = bool(
        all(
            operations[name]
            for name in (
                "available",
                "put",
                "read_match",
                "delete",
                "missing_after_delete",
                "finally_delete",
                "missing_after_finally",
            )
        )
        and result["cleanup_complete"]
    )
    result["status"] = "PASS" if success else "FAIL"
    if failure_type is not None:
        result["failure_type"] = failure_type
    if not result["cleanup_complete"]:
        # The account name is not secret material.  Emit it only on cleanup
        # failure so an operator can remove the exact orphan manually.
        result["cleanup_account"] = key
    return result, 0 if success else 1


def main() -> int:
    result, exit_code = asyncio.run(_probe())
    print(json.dumps(result, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
