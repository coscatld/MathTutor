"""Probe real Next -> uvicorn transport boundaries with disposable data.

Run with the project Python; Node and web/node_modules must be available.
Use --production after a frontend build, or omit it to start Next dev.
This does not open a browser or touch the user's data/keychain.
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def request(base, path, secret, *, headers=None, data=None):
    req = urllib.request.Request(base + path, headers=headers or {}, data=data)
    try:
        response = urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        body = response.read()
        assert secret.encode() not in body and secret not in str(response.headers)
        return response.status, body


def websocket_status(port, *, origin=None, secret=None):
    headers = [
        "GET /api/v2/math-tutor/ws HTTP/1.1", f"Host: 127.0.0.1:{port}",
        "Upgrade: websocket", "Connection: Upgrade", "Sec-WebSocket-Version: 13",
        "Sec-WebSocket-Key: " + base64.b64encode(os.urandom(16)).decode(),
    ]
    if origin is not None:
        headers.append("Origin: " + origin)
    if secret is not None:
        headers.append("X-MathTutor-Bridge: " + secret)
    with socket.create_connection(("127.0.0.1", port), timeout=8) as connection:
        connection.sendall(("\r\n".join(headers) + "\r\n\r\n").encode())
        first_line = b""
        while b"\r\n" not in first_line:
            chunk = connection.recv(4096)
            if not chunk:
                break
            first_line += chunk
        return first_line.split(b"\r\n")[0].decode()


def upload(port, secret, size, *, chunked):
    boundary = "MathTutorTransportProbe"
    opening = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
               'filename="probe.txt"\r\nContent-Type: text/plain\r\n\r\n').encode()
    body = opening + b"x" * size + f"\r\n--{boundary}--\r\n".encode()
    headers = {"X-MathTutor-Bridge": secret, "Content-Type": f"multipart/form-data; boundary={boundary}"}
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        data = (body[index:index + 65536] for index in range(0, len(body), 65536)) if chunked else body
        connection.request("POST", "/api/v2/math-tutor/desktop/documents/import",
                           body=data, headers=headers, encode_chunked=chunked)
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


def conversation_counts(database):
    with sqlite3.connect(database) as connection:
        return tuple(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                     for table in ("conversations", "conversation_messages"))


def stop(children):
    for child in children:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    for child in children:
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                os.killpg(child.pid, signal.SIGKILL)
            else:
                child.kill()
            child.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", action="store_true", help="use the completed Next production build")
    args = parser.parse_args()
    node = shutil.which("node")
    if node is None:
        parser.error("Node must be available on PATH")
    backend_port, frontend_port = free_port(), free_port()
    backend = f"http://127.0.0.1:{backend_port}"
    frontend = f"http://127.0.0.1:{frontend_port}"
    secret = secrets.token_hex(32)
    children, logs = [], []
    succeeded = False
    with tempfile.TemporaryDirectory(prefix="mathtutor-transport-probe-") as directory:
        database = Path(directory) / "math_tutor.db"
        env = dict(os.environ, MATHTUTOR_DATA_ROOT=directory, MATHTUTOR_DB_PATH=str(database),
                   MATHTUTOR_DESKTOP="1", MATHTUTOR_ENVIRONMENT="test", MATHTUTOR_AUTH_ENABLED="0",
                   AUTH_ENABLED="0", MATHTUTOR_ALLOWED_HOSTS=f"127.0.0.1:{backend_port}",
                   MATHTUTOR_ALLOWED_ORIGINS=frontend, MATHTUTOR_BRIDGE_SECRET=secret,
                   MATHTUTOR_API_BASE_URL=backend, MATHTUTOR_BROWSER_DEV="1",
                   MATHTUTOR_ELECTRON_PICKER_URL="", NEXT_TELEMETRY_DISABLED="1", PYTHONPATH=str(ROOT / "src"))
        commands = [
            ([sys.executable, "-m", "uvicorn", "--factory", "mathtutor.standalone:create_standalone_app",
              "--host", "127.0.0.1", "--port", str(backend_port), "--log-level", "warning"], ROOT),
            ([node, "node_modules/next/dist/bin/next", "start" if args.production else "dev",
              "--hostname", "127.0.0.1", "--port", str(frontend_port)], ROOT / "web"),
        ]
        credential = {"X-MathTutor-Bridge": secret}
        path = "/api/v2/math-tutor/sessions"
        try:
            for command, cwd in commands:
                log = tempfile.TemporaryFile()
                logs.append(log)
                children.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=log,
                                                 start_new_session=os.name != "nt"))
            for base, ready_path in [(backend, "/health"), (frontend, "/api/v2/auth/status")]:
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    assert all(child.poll() is None for child in children), "service exited during startup"
                    try:
                        if request(base, ready_path, secret, headers=credential)[0] == 200:
                            break
                    except (OSError, TimeoutError):
                        pass
                    time.sleep(0.25)
                else:
                    raise RuntimeError("service readiness timed out")
            assert request(frontend, path, secret, headers=credential)[0] == 200
            browser = {"X-MathTutor-CSRF": "1", "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Referer": frontend + "/math-tutor"}
            assert request(frontend, path, secret, headers=browser)[0] == 200
            before = conversation_counts(database)
            for base in (backend, frontend):
                assert request(base, path, secret)[0] == 403
                for origin in ("https://evil.example", "null", frontend + "0", frontend + ".evil.example"):
                    headers = {"Origin": origin, "Content-Type": "application/json", "X-MathTutor-CSRF": "1"}
                    assert request(base, path, secret, headers=headers, data=b'{"conversation_id":"attack"}')[0] == 403
                    port = backend_port if base == backend else frontend_port
                    assert "403" in websocket_status(port, origin=origin)
            assert conversation_counts(database) == before, "rejected requests created persistent conversations/messages"
            for port in (backend_port, frontend_port):
                assert "101" in websocket_status(port, origin=frontend)
                assert "403" in websocket_status(port)
                assert "101" in websocket_status(port, secret=secret)
            own = {"Origin": frontend, "Content-Type": "application/json", "X-MathTutor-CSRF": "1"}
            assert request(frontend, path, secret, headers=own, data=b'{"conversation_id":"allowed-session"}')[0] == 201
            with sqlite3.connect(database) as connection:
                assert connection.execute("SELECT COUNT(*) FROM conversations WHERE conversation_id='allowed-session'").fetchone()[0] == 1
            for port in (backend_port, frontend_port):
                for chunked in (False, True):
                    for size, expected in ((32, 200), (20 * MIB + 1, 413), (21 * MIB, 413)):
                        actual = upload(port, secret, size, chunked=chunked)
                        assert actual == expected, f"upload size={size} chunked={chunked}: HTTP {actual}"
            succeeded = True
        finally:
            stop(children)
            for log in logs:
                log.seek(0)
                output = log.read().decode(errors="replace")
                log.close()
                assert secret not in output, "bridge credential appeared in service output"
                if not succeeded:
                    print(output[-4000:], file=sys.stderr)
    print("PASS: real Next/uvicorn Host, Origin, CSRF, native credentials, WS handshake, SQLite rejection effects, "
          "secret-free responses/logs, and 12 direct/proxy content-length/chunked upload cases")


if __name__ == "__main__":
    main()
