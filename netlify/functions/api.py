import sys
import os
import base64

# 프로젝트 루트를 Python 경로에 추가
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _root)

from _server_core import handle_request


def handler(event, context):
    method  = event.get("httpMethod", "GET")
    path    = event.get("path", "/")
    headers = event.get("headers") or {}
    body    = event.get("body") or ""

    if event.get("isBase64Encoded"):
        body_bytes = base64.b64decode(body)
    elif isinstance(body, str):
        body_bytes = body.encode("utf-8")
    else:
        body_bytes = body or b""

    status, resp_headers, resp_body = handle_request(method, path, headers, body_bytes)

    resp_headers.setdefault("Access-Control-Allow-Origin", "*")
    resp_headers.setdefault("Cache-Control", "no-cache, no-store, must-revalidate")

    return {
        "statusCode": status,
        "headers": resp_headers,
        "body": resp_body.decode("utf-8") if isinstance(resp_body, bytes) else resp_body,
        "isBase64Encoded": False,
    }
