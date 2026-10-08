#!/usr/bin/env python3
"""성취기준(achievement_standard) 레코드를 임베딩해서 로컬에 캐싱한다.
API를 매번 호출하지 않도록, 한 번 만들어두고 embedding_search.py에서 재사용한다.

실행: python build_index.py              (전체 5789건 — 기기에 부담될 수 있음)
     python build_index.py --scope-golden (골든셋 질의가 쓰는 범위만, 가벼운 실험용)
출력: index/embeddings.npy (N x dim), index/meta.json (레코드 _id 목록, 같은 순서)
"""
import argparse
import json
import os

import numpy as np

from data_loader import filter_by_slots, load_records
from embedding_client import embed_texts

INDEX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index")
DOC_TYPE = "achievement_standard"
GOLDEN_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "docs", "topic-retrieval", "golden-set.jsonl",
)


def _scope_to_golden(records, golden_path=GOLDEN_PATH):
    """골든셋 질의들이 쓰는 (school_level, subject, course) 범위의 합집합만 남긴다."""
    scopes = set()
    with open(golden_path, encoding="utf-8") as f:
        for line in f:
            q = json.loads(line)
            if q["id"] == "example":
                continue
            scopes.add((q["school_level"], q["subject"], q["course"]))

    union_ids = set()
    for school_level, subject, course in scopes:
        scoped = filter_by_slots(records, school_level=school_level, subject=subject, course=course)
        union_ids.update(r["_id"] for r in scoped)
    return [r for r in records if r["_id"] in union_ids]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope-golden", action="store_true",
                     help="전체 대신 골든셋 질의 범위(12개 school_level/subject/course 조합)만 임베딩")
    args = ap.parse_args()

    os.makedirs(INDEX_DIR, exist_ok=True)

    records = load_records(doc_type=DOC_TYPE)
    if args.scope_golden:
        records = _scope_to_golden(records)
    print(f"임베딩 대상: {len(records)}건 ({DOC_TYPE}{' · 골든셋 범위' if args.scope_golden else ' · 전체'})")

    # 원래 "text"(해설+고려사항까지 포함, 최대 4400자대)로 임베딩했더니 5789건에
    # 4시간이 걸렸다. BM25 때 이미 검증한 "search_text"(content+area, 평균 30자대)로
    # 바꾸니 같은 작업이 ~5분으로 줄었다 (실측: 320건 워밍업 후 17초).
    texts = [r["search_text"] for r in records]
    vectors = embed_texts(texts)

    arr = np.array(vectors, dtype=np.float32)
    np.save(os.path.join(INDEX_DIR, "embeddings.npy"), arr)

    meta = [{"_id": r["_id"], "code": r.get("code"), "seq": r.get("seq")} for r in records]
    with open(os.path.join(INDEX_DIR, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    print(f"저장 완료: {arr.shape} -> {INDEX_DIR}/embeddings.npy")


if __name__ == "__main__":
    main()
