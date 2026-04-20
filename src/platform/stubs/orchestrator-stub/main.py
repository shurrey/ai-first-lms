"""Minimal stub orchestrator that responds to health checks.

Replaced by real orchestrator from Engine workstream when available.
"""
from __future__ import annotations

import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import json


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok","stub":true}')
        elif self.path == "/api/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: {\"event\":\"error\",\"payload\":{\"message\":\"stub orchestrator\"}}\n\n")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        if self.path in ("/api/converse", "/api/session", "/api/approval"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "stub": True}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"Orchestrator stub listening on :{port}")
    server.serve_forever()
