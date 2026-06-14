#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

PORT = int(os.getenv("PORT", 8080))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

STATIC_FILES = {
    "/":           ("index.html", "text/html"),
    "/index.html": ("index.html", "text/html"),
    "/index.css":  ("index.css",  "text/css"),
    "/index.js":   ("index.js",   "application/javascript"),
}


class LboxAdminHandler(BaseHTTPRequestHandler):

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def _dispatch(self):
        from _server_core import handle_request

        parsed = urlparse(self.path)
        path = parsed.path

        # OPTIONS preflight (인증 없이 허용)
        if self.command == "OPTIONS":
            self.send_response(200)
            self.end_headers()
            return

        # 정적 파일은 인증 없이 서빙 (로그인 화면이 index.html에 포함됨)
        if self.command == "GET" and path in STATIC_FILES:
            filename, content_type = STATIC_FILES[path]
            filepath = os.path.join(BASE_DIR, filename)
            if not os.path.exists(filepath):
                self.send_error(404, "Static file not found")
                return
            self.send_response(200)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.end_headers()
            with open(filepath, "rb") as f:
                self.wfile.write(f.read())
            return

        # API 라우트 → _server_core 위임 (인증은 handle_request 내부에서 처리)
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""

        status, resp_headers, resp_body = handle_request(
            self.command, self.path, dict(self.headers), body
        )

        self.send_response(status)
        for k, v in resp_headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(resp_body)

    do_GET = do_POST = do_OPTIONS = _dispatch

    def log_message(self, fmt, *args):
        print(f"[HTTP] {self.address_string()} - {fmt % args}")


def run_server():
    httpd = HTTPServer(("", PORT), LboxAdminHandler)
    print(f"{'=' * 50}")
    print(f"   [Lbox Scraper Dashboard]  http://localhost:{PORT}")
    print(f"{'=' * 50}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Server stopped.")
        sys.exit(0)


if __name__ == "__main__":
    run_server()
