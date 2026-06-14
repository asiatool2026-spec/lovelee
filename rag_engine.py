#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rag_engine.py — 판례 RAG 엔진

- ChromaDB 로컬 벡터DB + paraphrase-multilingual-MiniLM-L12-v2 (한국어 지원)
- 폴백: ChromaDB 실패 시 TF-IDF 키워드 유사도
"""

from __future__ import annotations

import os
import json
import glob
import math
import re
from typing import Any, Dict, List, Optional

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.getenv("LBOX_DATA_DIR",   os.path.join(BASE_DIR, "data", "lbox_cases"))
CHROMA_DIR = os.getenv("LBOX_CHROMA_DIR", os.path.join(BASE_DIR, "data", "chroma_db"))

COLLECTION_NAME = "lbox_cases"
EMBEDDING_MODEL = os.getenv("LBOX_EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")


# ──────────────────────────────────────────────
# 임베딩 함수
# ──────────────────────────────────────────────

def _get_embedding_function():
    try:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        print(f"[RAG] SentenceTransformer 임베딩 사용: {EMBEDDING_MODEL}")
        return SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)
    except Exception as e:
        print(f"[RAG] SentenceTransformer 로드 실패: {e} → ChromaDB 기본 임베딩 사용")
        return None


# ──────────────────────────────────────────────
# ChromaDB 싱글톤
# ──────────────────────────────────────────────

_chroma_client = None
_collection = None


def _get_collection():
    global _chroma_client, _collection
    if _collection is not None:
        return _collection

    import chromadb

    os.makedirs(CHROMA_DIR, exist_ok=True)
    _chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)

    ef = _get_embedding_function()
    kwargs: Dict[str, Any] = {"name": COLLECTION_NAME, "metadata": {"hnsw:space": "cosine"}}
    if ef is not None:
        kwargs["embedding_function"] = ef

    _collection = _chroma_client.get_or_create_collection(**kwargs)
    return _collection


# ──────────────────────────────────────────────
# TF-IDF 폴백
# ──────────────────────────────────────────────

class TFIDFFallback:
    def __init__(self):
        self._docs: List[dict] = []
        self._idf: Dict[str, float] = {}

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r"[가-힣a-zA-Z0-9]+", text)

    def _build_idf(self):
        N = len(self._docs)
        df: Dict[str, int] = {}
        for doc in self._docs:
            for term in set(self._tokenize(doc["text"])):
                df[term] = df.get(term, 0) + 1
        self._idf = {t: math.log((N + 1) / (cnt + 1)) + 1 for t, cnt in df.items()}

    def add(self, documents: List[str], metadatas: List[dict], ids: List[str]):
        for doc, meta, did in zip(documents, metadatas, ids):
            self._docs.append({"id": did, "text": doc, "meta": meta})
        self._build_idf()

    def _tfidf_vector(self, text: str) -> Dict[str, float]:
        tokens = self._tokenize(text)
        if not tokens:
            return {}
        tf: Dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        return {t: (cnt / len(tokens)) * self._idf.get(t, 1) for t, cnt in tf.items()}

    def _cosine(self, a: Dict[str, float], b: Dict[str, float]) -> float:
        keys = set(a) & set(b)
        if not keys:
            return 0.0
        dot = sum(a[k] * b[k] for k in keys)
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb) if na and nb else 0.0

    def query(self, query_text: str, n_results: int = 5) -> dict:
        qv = self._tfidf_vector(query_text)
        scored = []
        for doc in self._docs:
            dv = self._tfidf_vector(doc["text"])
            scored.append((self._cosine(qv, dv), doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:n_results]
        return {
            "ids":       [[d["id"]   for _, d in top]],
            "documents": [[d["text"] for _, d in top]],
            "metadatas": [[d["meta"] for _, d in top]],
            "distances": [[1 - s     for s, _ in top]],
        }

    def count(self) -> int:
        return len(self._docs)


_fallback: Optional[TFIDFFallback] = None


def _load_fallback() -> TFIDFFallback:
    global _fallback
    if _fallback is None:
        _fallback = TFIDFFallback()
        _populate_fallback(_fallback)
    return _fallback


def _populate_fallback(fb: TFIDFFallback):
    files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    docs, metas, ids = [], [], []
    for fp in files:
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
            cid = data.get("case_id", "")
            if not cid or not data.get("content"):
                continue
            docs.append(_build_document_text(data))
            metas.append(_build_metadata(data))
            ids.append(str(cid))
        except Exception:
            pass
    if docs:
        fb.add(docs, metas, ids)


# ──────────────────────────────────────────────
# 공통 유틸
# ──────────────────────────────────────────────

def _format_date(val) -> str:
    """ms 타임스탬프 또는 문자열을 'YYYY. MM. DD.' 형식으로 변환"""
    if not val:
        return ""
    try:
        ts = int(val)
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        return f"{dt.year}. {dt.month:02d}. {dt.day:02d}."
    except (ValueError, TypeError):
        return str(val)


def _build_document_text(data: dict) -> str:
    parts = [
        data.get("case_name", ""),
        data.get("case_number", ""),
        data.get("court", ""),
        (data.get("content", "") or "")[:2000],
    ]
    return " ".join(p for p in parts if p)


def _build_metadata(data: dict) -> dict:
    return {
        "case_number":     str(data.get("case_number", "") or ""),
        "court":           str(data.get("court", "") or ""),
        "judgment_date":   _format_date(data.get("judgment_date", "")),
        "case_name":       str(data.get("case_name", "") or ""),
        "content_preview": str(data.get("content", "") or "")[:300],
    }


# ──────────────────────────────────────────────
# 공개 API
# ──────────────────────────────────────────────

def index_cases(force: bool = False) -> dict:
    files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    if not files:
        return {"indexed": 0, "skipped": 0, "errors": 0, "total_in_db": 0, "message": "수집된 판례 파일 없음"}

    try:
        col = _get_collection()
        use_chroma = True
    except Exception as e:
        print(f"[RAG] ChromaDB 초기화 실패: {e} → TF-IDF 폴백")
        use_chroma = False

    indexed = skipped = errors = 0
    existing_ids: set = set()

    if use_chroma and not force:
        try:
            existing_ids = set(col.get(include=[])["ids"])
        except Exception:
            pass

    batch_docs, batch_metas, batch_ids = [], [], []
    BATCH_SIZE = 50

    def _flush():
        nonlocal indexed
        if not batch_docs:
            return
        if use_chroma:
            col.add(documents=batch_docs, metadatas=batch_metas, ids=batch_ids)
        indexed += len(batch_docs)
        batch_docs.clear()
        batch_metas.clear()
        batch_ids.clear()

    for fp in files:
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)

            cid = str(data.get("case_id", ""))
            if not cid or not data.get("content"):
                skipped += 1
                continue

            if not force and cid in existing_ids:
                skipped += 1
                continue

            batch_docs.append(_build_document_text(data))
            batch_metas.append(_build_metadata(data))
            batch_ids.append(cid)

            if len(batch_docs) >= BATCH_SIZE:
                _flush()

        except Exception as e:
            print(f"[RAG] 파일 처리 오류 ({fp}): {e}")
            errors += 1

    _flush()

    total = col.count() if use_chroma else (indexed + len(existing_ids))
    print(f"[RAG] 인덱싱 완료 — 신규: {indexed}, 스킵: {skipped}, 오류: {errors}, DB 총계: {total}")
    return {"indexed": indexed, "skipped": skipped, "errors": errors, "total_in_db": total}


def search_similar(query: str, n_results: int = 5) -> List[dict]:
    if not query.strip():
        return []

    try:
        col = _get_collection()
        n = min(n_results, max(1, col.count()))
        if n == 0:
            return []
        result = col.query(
            query_texts=[query],
            n_results=n,
            include=["metadatas", "distances", "documents"],
        )
        return _format_results(result)
    except Exception as e:
        print(f"[RAG] ChromaDB 쿼리 실패: {e} → TF-IDF 폴백")

    fb = _load_fallback()
    if fb.count() == 0:
        return []
    result = fb.query(query, n_results=n_results)
    return _format_results(result)


def _format_results(result: dict) -> List[dict]:
    out = []
    ids       = result.get("ids", [[]])[0]
    metas     = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    for cid, meta, dist in zip(ids, metas, distances):
        similarity = round(max(0.0, 1.0 - float(dist)), 4)
        out.append({
            "case_id":         cid,
            "case_number":     meta.get("case_number", ""),
            "court":           meta.get("court", ""),
            "judgment_date":   meta.get("judgment_date", ""),
            "case_name":       meta.get("case_name", ""),
            "content_preview": meta.get("content_preview", ""),
            "similarity_score": similarity,
        })
    return out


def get_index_status() -> dict:
    files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    total_files = len(files)

    try:
        col = _get_collection()
        indexed = col.count()
        engine = "chromadb"
    except Exception:
        fb = _load_fallback()
        indexed = fb.count()
        engine = "tfidf_fallback"

    return {
        "total_files": total_files,
        "indexed_count": indexed,
        "engine": engine,
        "ready": indexed > 0,
    }
