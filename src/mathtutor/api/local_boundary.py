"""Shared HTTP/WebSocket transport gate, before routing and request bodies."""

from __future__ import annotations

import hmac

from starlette.responses import JSONResponse

from mathtutor.security.settings import MathTutorSecuritySettings

BRIDGE_HEADER = b"x-mathtutor-bridge"
CSRF_HEADER = b"x-mathtutor-csrf"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class LocalBoundaryMiddleware:
    def __init__(self, app, settings: MathTutorSecuritySettings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send) -> None:
        kind = scope.get("type")
        if kind not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        # Reject duplicate security headers instead of taking an arbitrary one.
        headers: dict[bytes, list[bytes]] = {}
        for key, value in scope.get("headers", []):
            headers.setdefault(key.lower(), []).append(value)

        def one(name: bytes) -> str | None:
            values = headers.get(name, [])
            return values[0].decode("latin-1") if len(values) == 1 else None

        host = one(b"host")
        origin = one(b"origin")
        supplied = one(BRIDGE_HEADER)
        credential = bool(self.settings.bridge_secret and supplied and hmac.compare_digest(
            supplied.encode("utf-8"), self.settings.bridge_secret.encode("utf-8")))
        trusted_origin = origin in self.settings.allowed_origins
        valid = bool(host in self.settings.allowed_hosts) and all(
            len(headers.get(name, [])) <= 1 for name in (b"host", b"origin", BRIDGE_HEADER, CSRF_HEADER)
        )
        if b"origin" in headers:
            valid = valid and trusted_origin
        else:
            valid = valid and credential
        if kind == "http" and scope.get("method", "GET").upper() not in _SAFE_METHODS:
            # A custom header cannot be carried by a cross-site simple form.
            valid = valid and (credential or (trusted_origin and one(CSRF_HEADER) == "1"))
        if not valid:
            if kind == "websocket":
                # No accept, owner lookup, conversation creation or model call.
                await send({"type": "websocket.close", "code": 1008, "reason": "Untrusted request source"})
            else:
                await JSONResponse({"detail": "Untrusted request source"}, status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)


__all__ = ["LocalBoundaryMiddleware"]
