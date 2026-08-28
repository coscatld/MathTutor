"""Target-machine SecretStore sentinel for RC public release adapters.

The random value is generated inside this process and never accepted through
argv or an environment variable.  The report contains status only, never the
key value.  Cleanup is attempted in ``finally`` and a final missing read is a
required PASS condition.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import platform
import secrets

from mathtutor.infrastructure.keychain_secret_store import (
    KeychainSecretStore,
    KeychainSecretStoreError,
    KeychainUnavailableError,
    KeychainUnsupportedError,
)


async def _probe(expected_platform: str) -> tuple[dict[str, object], int]:
    actual = platform.system()
    if actual != expected_platform:
        return {
            "status": "UNTESTED",
            "reason_code": "TARGET_PLATFORM_MISMATCH",
            "platform": actual,
            "plaintext_fallback": False,
        }, 4

    store = KeychainSecretStore(service="com.mathtutor.product.rc-sentinel")
    key = f"release-smoke.{secrets.token_hex(16)}"
    value = secrets.token_urlsafe(48)
    unavailable = False
    report: dict[str, object]
    exit_code: int
    try:
        await store.put(key, value)
        if await store.get(key) != value:
            raise KeychainSecretStoreError("sentinel readback mismatch")
        await store.delete(key)
        if await store.get(key) is not None:
            raise KeychainSecretStoreError("sentinel remained after delete")
        report, exit_code = ({
            "status": "PASS",
            "reason_code": "WRITE_READ_DELETE_FINAL_MISSING",
            "platform": actual,
            "plaintext_fallback": False,
        }, 0)
    except (KeychainUnavailableError, KeychainUnsupportedError):
        unavailable = True
        report, exit_code = ({
            "status": "BLOCKED",
            "reason_code": "CREDENTIAL_STORE_UNAVAILABLE",
            "platform": actual,
            "plaintext_fallback": False,
        }, 3)
    except Exception:
        report, exit_code = ({
            "status": "FAIL",
            "reason_code": "CREDENTIAL_STORE_OPERATION_FAILED",
            "platform": actual,
            "plaintext_fallback": False,
        }, 1)
    finally:
        cleanup_error = False
        if not unavailable:
            try:
                await store.delete(key)
            except Exception:
                cleanup_error = True
        # Do not print or persist key/value. A cleanup failure is intentionally
        # observable only through the process failure; adapters must not PASS.
        if cleanup_error:
            report, exit_code = ({
                "status": "FAIL",
                "reason_code": "SENTINEL_CLEANUP_FAILED",
                "platform": actual,
                "plaintext_fallback": False,
            }, 1)
    return report, exit_code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-platform", choices=("Windows", "Linux"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report, exit_code = asyncio.run(_probe(args.expected_platform))
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
