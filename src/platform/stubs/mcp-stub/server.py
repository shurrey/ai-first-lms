"""Minimal stub MCP server that responds to health checks.

Replaced by real MCP servers from Data & MCP workstream when available.
"""
from __future__ import annotations

import os
from http.server import HTTPServer, BaseHTTPRequestHandler


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok","stub":true}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass  # suppress noisy logs


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "7000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"MCP stub listening on :{port}")
    server.serve_forever()
