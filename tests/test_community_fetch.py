import asyncio
import io
import socket
import ssl
from email.message import Message

import pytest

from mathtutor.application import community_fetch as fetch


@pytest.mark.parametrize("url", [
    "http://example.org/catalog.json", "https://user:pass@example.org/a", "https://example.org/a?token=secret",
    "https://example.org/a#part", "https://example.org/a?", "https://localhost/a", "https://127.0.0.1/a",
    "https://[::1]/a", "https://[::ffff:127.0.0.1]/a", "https://10.0.0.1/a", "https://169.254.169.254/a",
    "https://224.0.0.1/a", "https://router.local/a", "https://example.org\\@127.0.0.1/a",
    "https://example.org/a%0d%0aHost:evil", "https://example.org/a\n", "https://example.org:0/a",
    "https://[fec0::1]/a", "https://[64:ff9b::7f00:1]/a", "https://[2002:7f00:1::1]/a",
])
def test_source_url_rejects_credentials_private_hosts_and_ambiguous_urls(url):
    with pytest.raises(fetch.CommunityFetchError):
        fetch.validate_public_url(url)


def test_source_url_normalizes_host_port_and_unicode_path():
    assert fetch.validate_public_url("https://EXAMPLE.org.:443/数学.json") == "https://example.org/%E6%95%B0%E5%AD%A6.json"


class Response:
    def __init__(self, body=b'{"resources":[]}', *, status=200, headers=None):
        self.status, self.body = status, io.BytesIO(body)
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value

    def getheader(self, key, default=None):
        return self.headers.get(key, default)

    def read1(self, size):
        return self.body.read(size)


def transport(monkeypatch, response, addresses=("8.8.8.8",)):
    requests = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443)) for ip in addresses])
    class Connection:
        sock = None
        def __init__(self, host, port, *, address, timeout):
            self.record = {"host": host, "port": port, "address": address, "timeout": timeout}
            requests.append(self.record)
        def request(self, method, path, headers):
            self.record.update(method=method, path=path, headers=headers)
        def getresponse(self):
            return response
        def close(self):
            self.record["closed"] = True
    monkeypatch.setattr(fetch, "_PinnedHTTPSConnection", Connection)
    return requests


def test_download_pins_resolved_address_and_sends_no_credentials(monkeypatch):
    body = '{"题库":[]}'.encode()
    requests = transport(monkeypatch, Response(body, headers={"Content-Length": str(len(body))}))
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    assert asyncio.run(fetch.fetch_public_bytes("https://raw.example.org/catalog.json", max_bytes=1024)) == body
    assert len(requests) == 1
    assert requests[0]["address"] == "8.8.8.8"
    assert requests[0]["host"] == "raw.example.org"
    assert requests[0]["path"] == "/catalog.json"
    assert requests[0]["method"] == "GET"
    assert not {"Authorization", "Cookie", "Proxy-Authorization"} & requests[0]["headers"].keys()
    assert requests[0]["closed"] is True


def test_mixed_public_private_dns_never_opens_a_connection(monkeypatch):
    requests = transport(monkeypatch, Response(), addresses=("8.8.8.8", "127.0.0.1"))
    with pytest.raises(fetch.CommunityFetchError, match="公开互联网"):
        asyncio.run(fetch.fetch_public_bytes("https://rebind.example.org/catalog.json", max_bytes=1024))
    assert requests == []


@pytest.mark.parametrize("url,allowed", [
    ("https://raw.githubusercontent.com/catalog.json", True),
    ("https://raw.githubusercontent.com:8443/catalog.json", False),
    ("https://custom.example.org/catalog.json", False),
])
def test_existing_vpn_fake_ip_is_limited_to_fixed_official_github_tls_host(monkeypatch, url, allowed):
    requests = transport(monkeypatch, Response(), addresses=("198.18.0.10",))
    if allowed:
        asyncio.run(fetch.fetch_public_bytes(url, max_bytes=1024))
        assert requests[0]["host"] == "raw.githubusercontent.com"
        assert requests[0]["port"] == 443
    else:
        with pytest.raises(fetch.CommunityFetchError):
            asyncio.run(fetch.fetch_public_bytes(url, max_bytes=1024))
        assert requests == []


@pytest.mark.parametrize("response", [
    Response(status=302, headers={"Location": "https://127.0.0.1/private"}),
    Response(status=404), Response(headers={"Content-Encoding": "gzip"}),
    Response(headers={"Content-Length": "999999"}),
    Response(b"123456789"), Response(b"abc", headers={"Content-Length": "6"}),
    Response(headers={"Content-Length": "1,1"}),
    Response(headers={"Content-Length": "3", "Transfer-Encoding": "chunked"}),
])
def test_download_rejects_redirects_errors_compression_and_invalid_sizes(monkeypatch, response):
    requests = transport(monkeypatch, response)
    with pytest.raises(fetch.CommunityFetchError):
        asyncio.run(fetch.fetch_public_bytes("https://example.org/resource", max_bytes=8))
    assert len(requests) == 1  # Never follows a Location or retries a different URL.
    assert requests[0]["closed"] is True


@pytest.mark.parametrize("reject_certificate", [False, True], ids=["accepted", "rejected"])
def test_tls_uses_the_original_hostname_with_public_pinned_socket(monkeypatch, reject_certificate):
    recorded = {}
    class Socket:
        def close(self):
            recorded["closed"] = True
    raw = Socket()
    def connect(address, timeout):
        recorded.update(address=address, timeout=timeout)
        return raw
    monkeypatch.setattr(socket, "create_connection", connect)
    context = ssl.create_default_context()
    certificate_error = ssl.SSLCertVerificationError("certificate rejected")
    def wrap_socket(sock, *, server_hostname):
        # Keep the real SSLContext contract used by HTTPSConnection on 3.11/3.12.
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname is True
        recorded.update(server_hostname=server_hostname, wrapped=sock)
        if reject_certificate:
            raise certificate_error
        return raw
    monkeypatch.setattr(context, "wrap_socket", wrap_socket)
    monkeypatch.setattr(ssl, "create_default_context", lambda: context)
    connection = fetch._PinnedHTTPSConnection("raw.example.org", 443, address="8.8.8.8", timeout=2)
    assert connection._context is context
    if reject_certificate:
        with pytest.raises(ssl.SSLCertVerificationError) as raised:
            connection.connect()
        assert raised.value is certificate_error
        assert recorded["closed"] is True
        assert connection.sock is None
    else:
        connection.connect()
        assert connection.sock is raw
        assert "closed" not in recorded
    assert recorded["address"] == ("8.8.8.8", 443)
    assert recorded["timeout"] == 2
    assert recorded["server_hostname"] == "raw.example.org"
    assert recorded["wrapped"] is raw


def test_download_timeout_is_bounded_without_returning_remote_details(monkeypatch):
    def timeout(*a, **k):
        raise socket.timeout("private path or remote diagnostic must not escape")
    monkeypatch.setattr(socket, "getaddrinfo", timeout)
    with pytest.raises(fetch.CommunityFetchError) as raised:
        asyncio.run(fetch.fetch_public_bytes("https://example.org/catalog", max_bytes=1024, timeout_seconds=.1))
    assert "private path" not in str(raised.value)
