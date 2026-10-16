"""Public, explicitly requested community downloads with pinned DNS resolution.

No redirects, environment proxies, cookies or credentials. The socket connects
to an already validated address while TLS and Host retain the original name.
"""
from __future__ import annotations

import asyncio
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
from urllib.parse import quote, urlsplit, urlunsplit


class CommunityFetchError(ValueError):
    """A public error without response bodies, credentials or resolved IPs."""


_MAX_BYTES = 32 * 1024 * 1024
_SLOTS = threading.BoundedSemaphore(4)


def _public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
        if not address.is_global or any((address.is_loopback, address.is_private,
                address.is_link_local, address.is_multicast, address.is_reserved,
                address.is_unspecified, getattr(address, "is_site_local", False))):
            return False
        if isinstance(address, ipaddress.IPv6Address):
            if address in ipaddress.ip_network("64:ff9b::/96") or address in ipaddress.ip_network("64:ff9b:1::/48"):
                return False  # NAT64 can translate to a private IPv4 target.
            if address.ipv4_mapped and not _public_address(str(address.ipv4_mapped)):
                return False
            if address.sixtofour and not _public_address(str(address.sixtofour)):
                return False
            if address.teredo and not all(_public_address(str(ip)) for ip in address.teredo):
                return False
        return True
    except ValueError:
        return False


def validate_public_url(url: str) -> str:
    """Normalize a public HTTPS URL syntactically; fetching also validates DNS."""
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise CommunityFetchError("资源地址长度无效，请使用公开 HTTPS 原始文件地址。")
    if any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
        raise CommunityFetchError("资源地址不能包含空白、控制字符或反斜线。")
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port if parsed.port is not None else 443
        if (parsed.scheme != "https" or not host or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or "?" in url or "#" in url or not 1 <= port <= 65535):
            raise ValueError
        if "%" in host or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home")):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            host = host.encode("idna").decode("ascii")
            if (len(host) > 253 or "." not in host or any(not re.fullmatch(
                    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in host.split("."))):
                raise ValueError
        else:
            if not _public_address(str(address)):
                raise ValueError
            host = str(address)
        path = parsed.path or "/"
        if re.search(r"%(?:0[0-9a-f]|1[0-9a-f]|7f)|%(?![0-9a-f]{2})", path, flags=re.I):
            raise ValueError
        # Encode non-ASCII paths while preserving existing URL escapes.
        path = quote(path, safe="/%:@!$&'()*+,;=-._~")
        netloc = f"[{host}]" if ":" in host else host
        if port != 443:
            netloc += f":{port}"
        return urlunsplit(("https", netloc, path, "", ""))
    except (ValueError, UnicodeError):
        raise CommunityFetchError("只支持公开 HTTPS 地址；不能包含登录凭据、查询参数、内网地址或片段。") from None


def _resolve_public(host: str, port: int) -> str:
    try:
        entries = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except OSError:
        raise CommunityFetchError("资源源域名暂时无法解析，请检查地址后重试。") from None
    addresses = {entry[4][0] for entry in entries if entry[0] in {socket.AF_INET, socket.AF_INET6}}
    def allowed(value):
        if _public_address(value):
            return True
        # Some existing VPNs map GitHub to their RFC 2544 Fake-IP range.
        # Only the fixed official hostname/443 can use that DNS result; TLS
        # still authenticates raw.githubusercontent.com with the system CA.
        # Literal URLs, custom hosts and every other private range stay denied.
        address = ipaddress.ip_address(value)
        return host == "raw.githubusercontent.com" and port == 443 and address.version == 4 and address in ipaddress.ip_network("198.18.0.0/15")
    if not addresses or not all(allowed(value) for value in addresses):
        raise CommunityFetchError("资源源必须解析到公开互联网地址，不能访问本机或内网服务。")
    return sorted(addresses)[0]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, *, address: str, timeout: float):
        super().__init__(host, port=port, timeout=timeout, context=ssl.create_default_context())
        self._address = address

    def connect(self):
        # Never resolve self.host a second time (including after a DNS rebind).
        raw = socket.create_connection((self._address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _fetch(url: str, max_bytes: int, timeout_seconds: float) -> bytes:
    if not _SLOTS.acquire(blocking=False):
        raise CommunityFetchError("正在读取其他社区资源，请稍后重试。")
    connection = None
    timer = None
    deadline = time.monotonic() + timeout_seconds
    try:
        parsed = urlsplit(url)
        host, port = parsed.hostname, parsed.port or 443
        address = _resolve_public(host, port)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        connection = _PinnedHTTPSConnection(host, port, address=address, timeout=remaining)
        def stop_socket():
            # A total deadline also stops slow HTTP headers/body streams.
            sock = connection.sock
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            connection.close()
        timer = threading.Timer(remaining, stop_socket)
        timer.daemon = True
        timer.start()
        connection.request("GET", parsed.path or "/", headers={
            "Accept": "application/json, application/zip, application/octet-stream",
            "Accept-Encoding": "identity", "User-Agent": "MathTutor-Community/1",
        })
        response = connection.getresponse()
        if response.status != 200:
            if 300 <= response.status < 400:
                raise CommunityFetchError("资源地址发生重定向，请填写最终 HTTPS 原始文件地址。")
            raise CommunityFetchError("资源源未返回可用文件，请确认原始文件地址与访问权限。")
        if response.getheader("Content-Encoding", "identity").lower() not in {"identity", ""}:
            raise CommunityFetchError("资源源返回了不支持的传输压缩，请提供原始文件。")
        lengths = response.headers.get_all("Content-Length", [])
        if lengths:
            if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,12}", lengths[0]):
                raise CommunityFetchError("资源源返回了无效的文件大小。")
            if int(lengths[0]) > max_bytes:
                raise CommunityFetchError("社区资源超过允许的下载大小。")
            if response.getheader("Transfer-Encoding"):
                raise CommunityFetchError("资源源返回了不明确的传输长度。")
        content = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            chunk = response.read1(min(65536, max_bytes + 1 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > max_bytes:
                raise CommunityFetchError("社区资源超过允许的下载大小。")
        if lengths and len(content) != int(lengths[0]):
            raise CommunityFetchError("资源文件未完整下载，请重试。")
        return bytes(content)
    except CommunityFetchError:
        raise
    except (OSError, ValueError, http.client.HTTPException):
        raise CommunityFetchError("社区资源读取失败或超时，请检查网络和 HTTPS 地址后重试。") from None
    finally:
        if timer is not None:
            timer.cancel()
        if connection is not None:
            connection.close()
        _SLOTS.release()


async def fetch_public_bytes(url: str, *, max_bytes: int, timeout_seconds: float = 15) -> bytes:
    if type(max_bytes) is not int or not 0 < max_bytes <= _MAX_BYTES:
        raise CommunityFetchError("社区资源下载预算无效。")
    if type(timeout_seconds) not in {float, int} or not 0 < timeout_seconds <= 30:
        raise CommunityFetchError("社区资源读取时限无效。")
    normalized = validate_public_url(url)
    try:
        return await asyncio.wait_for(asyncio.to_thread(_fetch, normalized, max_bytes, float(timeout_seconds)),
                                      timeout=float(timeout_seconds) + 0.2)
    except TimeoutError:
        raise CommunityFetchError("社区资源读取超时，请稍后重试。") from None
