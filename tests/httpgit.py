"""Lokální smart-HTTP git server pro testy (CGI `git http-backend`, jen 127.0.0.1)."""

from __future__ import annotations

import http.server
import os
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


@dataclass
class GitHttpServer:
    root: Path
    port: int = 0
    requests: list[str] = field(default_factory=list)
    redirect_to: str | None = None  # absolutní URL prefix pro přesměrování (302)

    def url(self, repo: str, host: str = "127.0.0.1") -> str:
        return f"http://{host}:{self.port}/{repo}"


def _handler(server: GitHttpServer) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def _serve(self) -> None:
            server.requests.append(self.path)
            if server.redirect_to:
                self.send_response(302)
                self.send_header("Location", server.redirect_to + self.path)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            parts = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            env = {
                "PATH": os.environ.get("PATH", ""),
                "GIT_PROJECT_ROOT": str(server.root),
                "GIT_HTTP_EXPORT_ALL": "1",
                "REQUEST_METHOD": self.command,
                "PATH_INFO": parts.path,
                "QUERY_STRING": parts.query,
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": str(length),
                "REMOTE_ADDR": "127.0.0.1",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "HOME": str(server.root),
            }
            proto = self.headers.get("Git-Protocol")
            if proto:
                env["GIT_PROTOCOL"] = proto
            proc = subprocess.run(
                ["git", "http-backend"], input=body, capture_output=True, env=env, check=False
            )
            head, _, payload = proc.stdout.partition(b"\r\n\r\n")
            status = 200
            headers: list[tuple[str, str]] = []
            for line in head.decode("latin-1").split("\r\n"):
                if not line:
                    continue
                key, _, value = line.partition(":")
                if key.lower() == "status":
                    status = int(value.strip().split()[0])
                else:
                    headers.append((key, value.strip()))
            self.send_response(status)
            for key, value in headers:
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = _serve
        do_POST = _serve

        def log_message(self, *args: object) -> None:
            pass

    return Handler


@contextmanager
def git_http_server(root: Path) -> Iterator[GitHttpServer]:
    """Spustí server nad bare repy v `root` (URL `http://127.0.0.1:PORT/<repo>.git`)."""
    state = GitHttpServer(root)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    state.port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        httpd.shutdown()
        httpd.server_close()
