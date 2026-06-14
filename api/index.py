import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import BaseHTTPRequestHandler
from _server_core import handle_request


class handler(BaseHTTPRequestHandler):

    def _dispatch(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""

        status, resp_headers, resp_body = handle_request(
            self.command,
            self.path,
            dict(self.headers),
            body,
        )

        self.send_response(status)
        resp_headers.setdefault("Access-Control-Allow-Origin", "*")
        resp_headers.setdefault("Cache-Control", "no-cache, no-store, must-revalidate")
        for k, v in resp_headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(resp_body)

    do_GET     = _dispatch
    do_POST    = _dispatch
    do_OPTIONS = _dispatch

    def log_message(self, *args):
        pass
