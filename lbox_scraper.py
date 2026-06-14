#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lbox_scraper.py — 엘박스 판례 수집기

실제 API (JS 번들 역공학으로 확인):
  검색: POST https://lbox.kr/api/case/search  body: {query, page, pageSize}
  상세: GET  https://lbox.kr/api/case         params: {id}
  본문: case.section_list[].text 를 합산
"""

import os
import sys
import re
import time
import json
import random
import argparse
import requests
from dotenv import load_dotenv

load_dotenv()

LBOX_COOKIE        = os.getenv("LBOX_COOKIE", "")
LBOX_AUTHORIZATION = os.getenv("LBOX_AUTHORIZATION", "")
USER_AGENT         = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

BASE_URL        = "https://lbox.kr"
SEARCH_ENDPOINT = f"{BASE_URL}/api/case/search"
DETAIL_ENDPOINT = f"{BASE_URL}/api/case"

_DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "lbox_cases")
os.makedirs(_DEFAULT_DATA_DIR, exist_ok=True)


class LboxScraper:
    def __init__(self, cookie: str = None, data_dir: str = None):
        self._cookie_override = cookie or ""
        self.data_dir = data_dir or _DEFAULT_DATA_DIR
        os.makedirs(self.data_dir, exist_ok=True)
        self.session = requests.Session()
        self._setup_headers()

    def _setup_headers(self):
        effective_cookie = self._cookie_override or LBOX_COOKIE
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
            "Referer": f"{BASE_URL}/",
            "Origin": BASE_URL,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        local_auth = LBOX_AUTHORIZATION
        if effective_cookie and not local_auth:
            m = re.search(r"lboxToken=([^;]+)", effective_cookie)
            if m:
                local_auth = f"Bearer {m.group(1).strip()}"
                print("[INFO] lboxToken → Authorization Bearer 자동 구성")

        if local_auth:
            headers["Authorization"] = local_auth
            print("[INFO] Authorization 헤더 설정 완료")

        effective_cookie = self._cookie_override or LBOX_COOKIE
        if effective_cookie:
            headers["Cookie"] = effective_cookie
            print("[INFO] 세션 쿠키 주입 완료")
        else:
            print("[WARNING] 인증 정보 없음. 비로그인 상태로 요청합니다.")

        self.session.headers.update(headers)

    # ──────────────────────────────────────────────
    # 진단 모드
    # ──────────────────────────────────────────────
    def diagnose(self, keyword: str = "교통사고"):
        print("\n" + "=" * 60)
        print("  [DIAGNOSE] 엘박스 API 진단 모드")
        print("=" * 60)

        print(f"\n▶ 검색 API: POST {SEARCH_ENDPOINT}")
        try:
            r = self.session.post(
                SEARCH_ENDPOINT,
                json={"query": keyword, "page": 1, "pageSize": 3},
                timeout=8,
            )
            print(f"  HTTP {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                cases = data.get("caseList", [])
                print(f"  결과: {len(cases)}개 판례")
                if cases:
                    print(f"  샘플 ID: {cases[0].get('id')}")
                    print(f"  샘플 필드: {list(cases[0].keys())}")
            else:
                print(f"  응답: {r.text[:300]}")
        except Exception as e:
            print(f"  [ERROR] {e}")

        print(f"\n▶ 상세 API: GET {DETAIL_ENDPOINT}?id=...")
        try:
            r2 = self.session.post(
                SEARCH_ENDPOINT,
                json={"query": keyword, "page": 1, "pageSize": 1},
                timeout=8,
            )
            if r2.status_code == 200:
                cases = r2.json().get("caseList", [])
                if cases:
                    cid = cases[0]["id"]
                    r3 = self.session.get(DETAIL_ENDPOINT, params={"id": cid}, timeout=8)
                    print(f"  HTTP {r3.status_code} (ID: {cid})")
                    if r3.status_code == 200:
                        d = r3.json()
                        case = d.get("case", {})
                        sections = case.get("section_list", [])
                        text = "\n".join(s.get("text", "") for s in sections if s.get("text"))
                        print(f"  본문 길이: {len(text)}자")
                        print(f"  본문 미리보기: {text[:200]}")
        except Exception as e:
            print(f"  [ERROR] {e}")

        print("\n" + "=" * 60)

    # ──────────────────────────────────────────────
    # 검색
    # ──────────────────────────────────────────────
    def search_cases(self, keyword: str, limit: int = 10):
        print(f"[INFO] '{keyword}' 검색 중 (최대 {limit}개)...")

        try:
            resp = self.session.post(
                SEARCH_ENDPOINT,
                json={"query": keyword, "page": 1, "pageSize": limit},
                timeout=10,
            )

            if resp.status_code in (401, 403):
                print(f"[ERROR] 인증 실패 (HTTP {resp.status_code}). 쿠키를 갱신하세요.")
                return []

            resp.raise_for_status()
            data = resp.json()
            items = data.get("caseList", [])

            case_list = []
            for item in items:
                cid = item.get("id", "")
                if not cid:
                    continue
                # title 예: "서울중앙지방법원 2001. 12. 28. 선고 2001가단106906 판결 [보험금]"
                title = item.get("title", "")
                court = item.get("court", "")
                date  = item.get("announce_date", "")
                case_list.append({
                    "case_id":       cid,
                    "case_number":   item.get("sub_title") or title,
                    "court":         court,
                    "judgment_date": date,
                    "case_name":     item.get("casename") or title,
                })

            print(f"[INFO] {len(case_list)}개 판례 확보")
            return case_list

        except Exception as e:
            print(f"[ERROR] 검색 실패: {e}")
            return []

    # ──────────────────────────────────────────────
    # 상세 수집
    # ──────────────────────────────────────────────
    def get_case_detail(self, case_id: str):
        print(f"[INFO] 상세 수집: {case_id}")
        try:
            resp = self.session.get(DETAIL_ENDPOINT, params={"id": case_id}, timeout=10)

            if resp.status_code in (401, 403):
                print(f"[ERROR] 권한 없음 (HTTP {resp.status_code})")
                return None

            resp.raise_for_status()
            data = resp.json()
            case = data.get("case", {})

            # 본문: section_list[].text 합산
            sections = case.get("section_list", [])
            content = "\n".join(s.get("text", "") for s in sections if s.get("text"))

            if not content:
                print(f"[WARNING] 본문 없음: {case_id}")
                return None

            return {
                "case_id":       case_id,
                "case_number":   case.get("caseno_list", [case_id])[0] if case.get("caseno_list") else case_id,
                "court":         case.get("court", ""),
                "judgment_date": case.get("announce_date", ""),
                "case_name":     case.get("casename", "") or case.get("case", ""),
                "content":       content,
                "raw_json":      case,
            }

        except Exception as e:
            print(f"[ERROR] 상세 수집 실패 ({case_id}): {e}")
            return None

    # ──────────────────────────────────────────────
    # 저장
    # ──────────────────────────────────────────────
    def save_case(self, case_data: dict) -> bool:
        if not case_data or "case_id" not in case_data:
            return False
        filepath = os.path.join(self.data_dir, f"{case_data['case_id']}.json")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(case_data, f, ensure_ascii=False, indent=2)
            print(f"[SUCCESS] 저장: {filepath}")
            return True
        except Exception as e:
            print(f"[ERROR] 저장 실패: {e}")
            return False


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Lbox 판례 수집기")
    parser.add_argument("--keyword",  type=str,   default="교통사고")
    parser.add_argument("--limit",    type=int,   default=5)
    parser.add_argument("--delay",    type=float, default=2.0)
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()

    scraper = LboxScraper()

    if args.diagnose:
        scraper.diagnose(args.keyword)
        return

    case_list = scraper.search_cases(args.keyword, limit=args.limit)
    if not case_list:
        print("[WARNING] 검색 결과 없음.")
        sys.exit(1)

    print(f"\n[INFO] {len(case_list)}개 본문 수집 시작 (딜레이: {args.delay}초)")
    success = 0

    for idx, meta in enumerate(case_list):
        cid = meta["case_id"]
        print(f"\n--- [{idx + 1}/{len(case_list)}] ID: {cid} ---")

        target = os.path.join(scraper.data_dir, f"{cid}.json")
        if os.path.exists(target):
            print("[INFO] 이미 수집됨, 스킵")
            success += 1
            continue

        detail = scraper.get_case_detail(cid)
        if detail:
            for k in ["case_number", "court", "judgment_date", "case_name"]:
                if not detail.get(k) and meta.get(k):
                    detail[k] = meta[k]
            if scraper.save_case(detail):
                success += 1
        else:
            print(f"[WARNING] 본문 수집 실패: {cid}")

        time.sleep(max(0.5, args.delay + random.uniform(-0.5, 1.0)))

    print(f"\n{'=' * 40}")
    print(f"[완료] {len(case_list)}개 중 {success}개 수집 성공")
    print(f"저장 경로: {scraper.data_dir}")
    print(f"{'=' * 40}")


if __name__ == "__main__":
    main()
