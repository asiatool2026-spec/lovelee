import sys
import os
import base64
import json

# 프로젝트 루트를 Python 경로에 추가
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _root)


def _make_token(user: str, pwd: str) -> str:
    import hmac, hashlib
    return hmac.new(pwd.encode(), user.encode(), hashlib.sha256).hexdigest()


def _ok(data: dict):
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json; charset=utf-8",
                    "Access-Control-Allow-Origin": "*"},
        "body": json.dumps(data, ensure_ascii=False),
    }


def _err(status: int, msg: str):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8",
                    "Access-Control-Allow-Origin": "*"},
        "body": json.dumps({"status": "unauthorized", "message": msg}, ensure_ascii=False),
    }


def handler(event, context):
    method  = event.get("httpMethod", "GET")
    path    = event.get("path", "/")
    headers = event.get("headers") or {}
    body_raw = event.get("body") or ""

    if event.get("isBase64Encoded"):
        body_bytes = base64.b64decode(body_raw)
    elif isinstance(body_raw, str):
        body_bytes = body_raw.encode("utf-8")
    else:
        body_bytes = body_raw or b""

    # OPTIONS (CORS preflight)
    if method == "OPTIONS":
        return {
            "statusCode": 200,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
            },
            "body": "",
        }

    DASHBOARD_USER = os.getenv("DASHBOARD_USERNAME", "lovelee")
    DASHBOARD_PASS = os.getenv("DASHBOARD_PASSWORD", "230107")

    # 로그인 엔드포인트 — _server_core 없이 직접 처리
    clean_path = path.split("?")[0].rstrip("/")
    if method == "POST" and clean_path in ("/api/login", "/.netlify/functions/api/login"):
        try:
            payload  = json.loads(body_bytes)
            username = payload.get("username", "").strip()
            password = payload.get("password", "").strip()
        except Exception:
            return _err(400, "요청 형식 오류")

        if not DASHBOARD_PASS:
            return _ok({"token": ""})

        if username == DASHBOARD_USER and password == DASHBOARD_PASS:
            return _ok({"token": _make_token(DASHBOARD_USER, DASHBOARD_PASS)})

        return _err(401, "아이디 또는 비밀번호가 올바르지 않습니다.")

    # 나머지 요청 — _server_core 에 위임
    try:
        from _server_core import handle_request
        status, resp_headers, resp_body = handle_request(method, path, headers, body_bytes)
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json; charset=utf-8",
                        "Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": str(e)}, ensure_ascii=False),
        }

    resp_headers.setdefault("Access-Control-Allow-Origin", "*")
    resp_headers.setdefault("Cache-Control", "no-cache, no-store, must-revalidate")

    return {
        "statusCode": status,
        "headers": resp_headers,
        "body": resp_body.decode("utf-8") if isinstance(resp_body, bytes) else resp_body,
        "isBase64Encoded": False,
    }
