"""Minimal stub frontend that responds to health checks.

Replaced by real Next.js frontend from Frontend workstream when available.
"""
from __future__ import annotations

import os
from http.server import HTTPServer, BaseHTTPRequestHandler


class FrontendHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok","stub":true}')
        elif self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>AI-First LMS &mdash; Stub Frontend</h1>"
                             b"<p>Waiting for Frontend workstream.</p></body></html>")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "3000"))
    server = HTTPServer(("0.0.0.0", port), FrontendHandler)
    print(f"Frontend stub listening on :{port}")
    server.serve_forever()
