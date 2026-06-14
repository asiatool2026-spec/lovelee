#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_server_core.py — 플랫폼 독립 비즈니스 로직
  반환값: (status_code: int, headers: dict, body: bytes)
  Vercel(api/index.py), Netlify(netlify/functions/api.py), app.py 모두가 이 모듈을 호출합니다.
"""
from __future__ import annotations

import os
import sys
import json
import glob
import base64
import subprocess
from dotenv import load_dotenv
load_dotenv()
import threading
from datetime import datetime, timezone
from typing import Dict, Tuple, Any

# ──────────────────────────────────────────────
# 플랫폼 감지 및 경로 설정
# ──────────────────────────────────────────────

IS_SERVERLESS = bool(os.getenv("VERCEL") or os.getenv("NETLIFY"))
_BASE = os.path.dirname(os.path.abspath(__file__))

DATA_DIR    = os.getenv("LBOX_DATA_DIR",    "/tmp/lbox_cases"       if IS_SERVERLESS else os.path.join(_BASE, "data", "lbox_cases"))
CONFIG_PATH = os.getenv("LBOX_CONFIG_PATH", "/tmp/lbox_config.json" if IS_SERVERLESS else os.path.join(_BASE, ".env"))
LOG_PATH    = os.getenv("LBOX_LOG_PATH",    "/tmp/crawler.log"      if IS_SERVERLESS else os.path.join(_BASE, "data", "lbox_cases", "crawler.log"))

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

# ──────────────────────────────────────────────
# 인증
# ──────────────────────────────────────────────

DASHBOARD_USER = os.getenv("DASHBOARD_USERNAME", "admin")
DASHBOARD_PASS = os.getenv("DASHBOARD_PASSWORD", "")


def _check_auth(headers: dict) -> bool:
    if not DASHBOARD_PASS:
        return True
    auth = headers.get("Authorization") or headers.get("authorization") or ""
    # Bearer 토큰 (커스텀 로그인)
    if auth.startswith("Bearer "):
        return _check_token(auth[7:])
    # Basic Auth (하위 호환)
    if auth.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            user, pwd = decoded.split(":", 1)
            return user == DASHBOARD_USER and pwd == DASHBOARD_PASS
        except Exception:
            return False
    return False


def _unauthorized() -> Tuple[int, dict, bytes]:
    return (
        401,
        {"Content-Type": "application/json; charset=utf-8"},
        json.dumps({"status": "unauthorized"}, ensure_ascii=False).encode(),
    )


def _make_token() -> str:
    import hmac, hashlib
    if not DASHBOARD_PASS:
        return ""
    return hmac.new(DASHBOARD_PASS.encode(), DASHBOARD_USER.encode(), hashlib.sha256).hexdigest()


def _check_token(token: str) -> bool:
    if not DASHBOARD_PASS:
        return True
    return token == _make_token()


def handle_login(body: bytes) -> Tuple[int, dict, bytes]:
    try:
        payload = json.loads(body)
        username = payload.get("username", "").strip()
        password = payload.get("password", "").strip()
    except Exception:
        return _json_err(400, "요청 형식 오류")

    if not DASHBOARD_PASS:
        # 비밀번호 미설정 시 항상 통과
        return _json_ok({"token": ""})

    if username == DASHBOARD_USER and password == DASHBOARD_PASS:
        return _json_ok({"token": _make_token()})

    return 401, {"Content-Type": "application/json; charset=utf-8"},         json.dumps({"status": "unauthorized"}, ensure_ascii=False).encode()


# ──────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────

def _json_ok(data: Any) -> Tuple[int, dict, bytes]:
    return 200, {"Content-Type": "application/json; charset=utf-8"}, json.dumps(data, ensure_ascii=False).encode()


def _json_err(status: int, msg: str) -> Tuple[int, dict, bytes]:
    return status, {"Content-Type": "application/json; charset=utf-8"}, json.dumps({"status": "error", "message": msg}, ensure_ascii=False).encode()


def _format_date(val) -> str:
    if not val:
        return ""
    try:
        ts = int(val)
        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        return f"{dt.year}. {dt.month:02d}. {dt.day:02d}."
    except (ValueError, TypeError):
        return str(val)


# ──────────────────────────────────────────────
# 쿠키 읽기/쓰기
# ──────────────────────────────────────────────

def _get_cookie() -> str:
    # 1. 서버리스: /tmp/lbox_config.json (UI에서 업데이트한 값)
    if IS_SERVERLESS and os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                data = json.load(f)
            if data.get("cookie"):
                return data["cookie"]
        except Exception:
            pass
    # 2. .env 파일
    if not IS_SERVERLESS and os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                for line in f:
                    if line.strip().startswith("LBOX_COOKIE="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    # 3. 환경변수 (Vercel/Netlify 대시보드에서 설정)
    return os.getenv("LBOX_COOKIE", "")


def _save_cookie(cookie: str):
    if IS_SERVERLESS:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump({"cookie": cookie}, f)
    else:
        env_lines = []
        written = False
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH) as f:
                for line in f:
                    if line.strip().startswith("LBOX_COOKIE="):
                        env_lines.append(f'LBOX_COOKIE="{cookie}"\n')
                        written = True
                    else:
                        env_lines.append(line)
        if not written:
            env_lines.append(f'LBOX_COOKIE="{cookie}"\n')
        with open(CONFIG_PATH, "w") as f:
            f.writelines(env_lines)


# ──────────────────────────────────────────────
# 크롤러 상태 (로컬 전용)
# ──────────────────────────────────────────────

_active_process = None


# ──────────────────────────────────────────────
# 핸들러 함수들
# ──────────────────────────────────────────────

def handle_cases_list() -> Tuple[int, dict, bytes]:
    files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    cases = []
    for fp in files:
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
            raw_date = data.get("judgment_date") or data.get("judgmentDate") or ""
            cases.append({
                "case_id":          data.get("case_id"),
                "case_number":      data.get("case_number") or "알 수 없음",
                "court":            data.get("court") or "",
                "judgment_date":    _format_date(raw_date),
                "judgment_date_raw": raw_date,
                "case_name":        data.get("case_name") or "",
                "snippet":          (data.get("content", "") or "")[:120] + "..." if data.get("content") else "",
            })
        except Exception:
            pass
    cases.sort(key=lambda x: x.get("judgment_date_raw") or "", reverse=True)
    return _json_ok({"cases": cases})


def handle_case_detail(case_id: str) -> Tuple[int, dict, bytes]:
    case_id = os.path.basename(case_id)
    fp = os.path.join(DATA_DIR, f"{case_id}.json")
    if not os.path.exists(fp):
        return _json_err(404, "Case not found")
    with open(fp, encoding="utf-8") as f:
        return _json_ok(json.load(f))


def handle_config_get() -> Tuple[int, dict, bytes]:
    cookie = _get_cookie()
    return _json_ok({
        "cookie_exists": bool(cookie),
        "cookie_preview": cookie[:15] + "..." if len(cookie) > 15 else cookie,
    })


def handle_config_post(body: bytes) -> Tuple[int, dict, bytes]:
    try:
        payload = json.loads(body)
        cookie = payload.get("cookie", "").strip()
        _save_cookie(cookie)
        return _json_ok({"status": "success", "message": "Cookie saved."})
    except Exception as e:
        return _json_err(500, str(e))


def handle_crawl(body: bytes) -> Tuple[int, dict, bytes]:
    global _active_process
    try:
        payload = json.loads(body) if body else {}
    except Exception:
        payload = {}

    keyword = payload.get("keyword", "교통사고").strip()
    limit   = int(payload.get("limit", 5))
    delay   = float(payload.get("delay", 0.0))

    # 새 검색 시 기존 수집 자료 초기화
    for fp in glob.glob(os.path.join(DATA_DIR, "*.json")):
        try:
            os.remove(fp)
        except Exception:
            pass

    if IS_SERVERLESS:
        # 동기 실행: 완료 후 응답
        return _crawl_sync(keyword, limit, delay)
    else:
        # 비동기: subprocess
        return _crawl_async(keyword, limit, delay)


def _crawl_sync(keyword: str, limit: int, delay: float) -> Tuple[int, dict, bytes]:
    """서버리스용 동기 크롤링"""
    log_lines = []

    def log(msg):
        log_lines.append(msg)

    try:
        sys.path.insert(0, _BASE)
        from lbox_scraper import LboxScraper

        log(f"[INFO] 크롤링 시작: '{keyword}' (최대 {limit}개)")
        scraper = LboxScraper(cookie=_get_cookie(), data_dir=DATA_DIR)
        case_list = scraper.search_cases(keyword, limit=limit)

        if not case_list:
            log("[WARNING] 검색 결과 없음.")
            return _json_ok({"status": "done", "success": 0, "total": 0, "log": "\n".join(log_lines)})

        success = 0
        for idx, meta in enumerate(case_list):
            cid = meta["case_id"]
            fp = os.path.join(DATA_DIR, f"{cid}.json")
            if os.path.exists(fp):
                log(f"[{idx+1}/{len(case_list)}] 스킵 (이미 수집됨): {cid}")
                success += 1
                continue
            detail = scraper.get_case_detail(cid)
            if detail:
                for k in ["case_number", "court", "judgment_date", "case_name"]:
                    if not detail.get(k) and meta.get(k):
                        detail[k] = meta[k]
                scraper.save_case(detail)
                log(f"[{idx+1}/{len(case_list)}] 저장 완료: {cid}")
                success += 1
            else:
                log(f"[{idx+1}/{len(case_list)}] 실패: {cid}")

        log(f"[완료] {success}/{len(case_list)}개 수집 성공")
        full_log = "\n".join(log_lines)

        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.write(full_log)

        return _json_ok({"status": "done", "success": success, "total": len(case_list), "log": full_log})

    except Exception as e:
        return _json_err(500, str(e))


def _crawl_async(keyword: str, limit: int, delay: float) -> Tuple[int, dict, bytes]:
    """로컬용 비동기 subprocess 크롤링"""
    global _active_process
    if _active_process and _active_process.poll() is None:
        return _json_err(409, "이미 크롤링이 실행 중입니다.")

    with open(LOG_PATH, "w", encoding="utf-8") as f:
        f.write(f"[INFO] 크롤링 시작: {keyword}\n")

    log_writer = open(LOG_PATH, "a", encoding="utf-8")
    script = os.path.join(_BASE, "lbox_scraper.py")
    cmd = ["python3", script, "--keyword", keyword, "--limit", str(limit), "--delay", str(delay)]
    _active_process = subprocess.Popen(cmd, stdout=log_writer, stderr=log_writer, text=True)
    return _json_ok({"status": "started", "message": "크롤러가 백그라운드에서 시작되었습니다."})


def handle_logs() -> Tuple[int, dict, bytes]:
    global _active_process
    is_running = False
    if not IS_SERVERLESS and _active_process:
        if _active_process.poll() is None:
            is_running = True
        else:
            _active_process = None

    log_content = "대기 중..."
    if os.path.exists(LOG_PATH):
        try:
            with open(LOG_PATH, encoding="utf-8") as f:
                log_content = f.read()
        except Exception:
            pass

    return _json_ok({"status": "running" if is_running else "idle", "logs": log_content})


def handle_diagnose() -> Tuple[int, dict, bytes]:
    script = os.path.join(_BASE, "lbox_scraper.py")
    try:
        result = subprocess.run(
            ["python3", script, "--diagnose"],
            capture_output=True, text=True, timeout=30
        )
        output = (result.stdout or "") + (result.stderr or "")
        return _json_ok({"status": "ok", "output": output})
    except subprocess.TimeoutExpired:
        return _json_err(500, "진단 타임아웃 (30초 초과)")
    except Exception as e:
        return _json_err(500, str(e))


def handle_rag_status() -> Tuple[int, dict, bytes]:
    try:
        sys.path.insert(0, _BASE)
        from rag_engine import get_index_status
        return _json_ok(get_index_status())
    except Exception as e:
        return _json_ok({"total_files": 0, "indexed_count": 0, "engine": "unavailable", "ready": False, "message": str(e)})


def handle_rag_index(body: bytes) -> Tuple[int, dict, bytes]:
    try:
        payload = json.loads(body) if body else {}
        force = bool(payload.get("force", False))
    except Exception:
        force = False

    if IS_SERVERLESS:
        # 서버리스: 동기 실행
        try:
            sys.path.insert(0, _BASE)
            from rag_engine import index_cases
            result = index_cases(force=force)
            return _json_ok({"status": "done", **result})
        except Exception as e:
            return _json_err(500, str(e))
    else:
        # 로컬: 백그라운드 스레드
        def _do():
            sys.path.insert(0, _BASE)
            from rag_engine import index_cases
            index_cases(force=force)
        threading.Thread(target=_do, daemon=True).start()
        return _json_ok({"status": "started", "message": "인덱싱이 백그라운드에서 시작되었습니다."})


def handle_rag_search(body: bytes) -> Tuple[int, dict, bytes]:
    try:
        payload = json.loads(body)
        query = payload.get("query", "").strip()
        n = int(payload.get("n_results", 5))
    except Exception:
        return _json_err(400, "요청 형식 오류")

    if not query:
        return _json_err(400, "query 필드가 비어 있습니다.")

    try:
        sys.path.insert(0, _BASE)
        from rag_engine import search_similar
        results = search_similar(query, n_results=n)
        return _json_ok({"status": "ok", "query": query, "results": results})
    except Exception as e:
        return _json_err(500, str(e))


# ──────────────────────────────────────────────
# 메인 라우터
# ──────────────────────────────────────────────

def handle_request(method: str, path: str, headers: dict, body: bytes) -> Tuple[int, dict, bytes]:
    # CORS preflight
    if method == "OPTIONS":
        return 200, {
            "Access-Control-Allow-Origin":  "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        }, b""

    # 로그인 엔드포인트 (인증 불필요)
    clean_path_early = path.split("?")[0].rstrip("/")
    if method == "POST" and clean_path_early == "/api/login":
        return handle_login(body)

    # 인증 확인
    if not _check_auth(headers):
        return _unauthorized()

    # 경로에서 쿼리스트링 제거
    clean_path = path.split("?")[0].rstrip("/")

    # ── GET ──
    if method == "GET":
        if clean_path == "/api/cases":
            return handle_cases_list()
        if clean_path.startswith("/api/cases/"):
            return handle_case_detail(clean_path[len("/api/cases/"):])
        if clean_path == "/api/config":
            return handle_config_get()
        if clean_path == "/api/logs":
            return handle_logs()
        if clean_path == "/api/diagnose":
            return handle_diagnose()
        if clean_path == "/api/rag/status":
            return handle_rag_status()
        if clean_path == "/api/research":
            return handle_research()

    # ── POST ──
    if method == "POST":
        if clean_path == "/api/crawl":
            return handle_crawl(body)
        if clean_path == "/api/config":
            return handle_config_post(body)
        if clean_path == "/api/rag/index":
            return handle_rag_index(body)
        if clean_path == "/api/rag/search":
            return handle_rag_search(body)

    return _json_err(404, f"Not found: {method} {path}")


# ──────────────────────────────────────────────
# 리서치 결과 문서 생성
# ──────────────────────────────────────────────

def handle_research() -> Tuple[int, dict, bytes]:
    """수집된 판례를 종합해 1장 분량의 리서치 문서를 반환합니다."""
    from datetime import datetime, timezone

    files = sorted(glob.glob(os.path.join(DATA_DIR, "*.json")))
    if not files:
        return _json_ok({"document": "", "count": 0, "message": "수집된 판례가 없습니다."})

    cases = []
    for fp in files:
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
            if not data.get("content"):
                continue
            cases.append(data)
        except Exception:
            pass

    if not cases:
        return _json_ok({"document": "", "count": 0, "message": "본문이 있는 판례가 없습니다."})

    today = datetime.now(tz=timezone.utc)
    date_str = f"{today.year}. {today.month:02d}. {today.day:02d}."

    lines = []
    lines.append("=" * 60)
    lines.append(f"  판례 리서치 결과")
    lines.append(f"  수집 건수: {len(cases)}건  /  생성일: {date_str}")
    lines.append("=" * 60)
    lines.append("")

    for i, d in enumerate(cases, 1):
        case_number   = d.get("case_number", "사건번호 미상")
        court         = d.get("court", "")
        case_name     = d.get("case_name", "")
        raw_date      = d.get("judgment_date", "")
        judgment_date = _format_date(raw_date) if str(raw_date).isdigit() else str(raw_date)
        content       = (d.get("content") or "").strip()

        # 본문에서 핵심 단락 추출 (최대 600자)
        paragraphs = [p.strip() for p in content.split("\n") if len(p.strip()) > 20]
        excerpt = ""
        for p in paragraphs:
            if len(excerpt) + len(p) > 600:
                break
            excerpt += p + "\n"
        excerpt = excerpt.strip()

        lines.append(f"[{i}] {case_number}  /  {court}  /  {judgment_date}")
        if case_name:
            lines.append(f"    사건명: {case_name}")
        lines.append("")
        if excerpt:
            for row in excerpt.split("\n"):
                lines.append(f"    {row}")
        lines.append("")
        lines.append("-" * 60)
        lines.append("")

    document = "\n".join(lines)
    return _json_ok({"document": document, "count": len(cases)})
