#!/usr/bin/env python3
"""성취기준(achievement_standard) 레코드를 전부 임베딩해서 로컬에 캐싱한다.
API를 매번 호출하지 않도록, 한 번 만들어두고 embedding_search.py에서 재사용한다.

실행: python build_index.py
출력: index/embeddings.npy (N x dim), index/meta.json (레코드 _id 목록, 같은 순서)
"""
import json
import os

import numpy as np

from data_loader import load_records
from embedding_client import embed_texts

INDEX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index")
DOC_TYPE = "achievement_standard"


def main():
    os.makedirs(INDEX_DIR, exist_ok=True)

    records = load_records(doc_type=DOC_TYPE)
    print(f"임베딩 대상: {len(records)}건 ({DOC_TYPE})")

    texts = [r["text"] for r in records]
    vectors = embed_texts(texts)

    arr = np.array(vectors, dtype=np.float32)
    np.save(os.path.join(INDEX_DIR, "embeddings.npy"), arr)

    meta = [{"_id": r["_id"], "code": r.get("code"), "seq": r.get("seq")} for r in records]
    with open(os.path.join(INDEX_DIR, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

    print(f"저장 완료: {arr.shape} -> {INDEX_DIR}/embeddings.npy")


if __name__ == "__main__":
    main()
