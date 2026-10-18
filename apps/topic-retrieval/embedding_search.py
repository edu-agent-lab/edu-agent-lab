"""build_index.py가 만든 캐시로 임베딩 유사도 검색을 한다."""
import json
import os

import numpy as np

from embedding_client import embed_query

INDEX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index")


class EmbeddingIndex:
    def __init__(self, index_dir=INDEX_DIR):
        emb_path = os.path.join(index_dir, "embeddings.npy")
        meta_path = os.path.join(index_dir, "meta.json")
        if not os.path.exists(emb_path):
            raise FileNotFoundError(
                f"{emb_path} 가 없습니다. 먼저 `python build_index.py`로 인덱스를 만드세요."
            )
        self.vectors = np.load(emb_path)  # (N, dim)
        # 코사인 유사도를 내적으로 계산할 수 있게 미리 정규화해둔다.
        norms = np.linalg.norm(self.vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1e-8
        self.normed = self.vectors / norms
        with open(meta_path, encoding="utf-8") as f:
            self.meta = json.load(f)  # [{"_id":..., "code":..., "seq":...}, ...] 벡터와 같은 순서

    def search(self, query, records_by_id, top_k=20, allowed_ids=None):
        """query 임베딩과 코사인 유사도 상위 top_k를 반환한다.
        records_by_id: {_id: record} — data_loader.load_records() 결과로 만들어서 넘긴다.
        allowed_ids: 학년/과목 등으로 1차 필터링된 _id 집합. 주면 그 안에서만 검색한다
        (예: 벡터는 전체 성취기준으로 미리 만들어두고, 검색은 고등학교·사회로만 좁히는 식)."""
        qvec = np.array(embed_query(query), dtype=np.float32)
        qvec = qvec / (np.linalg.norm(qvec) + 1e-8)

        sims = self.normed @ qvec  # (N,)
        if allowed_ids is not None:
            mask = np.array([m["_id"] in allowed_ids for m in self.meta])
            sims = np.where(mask, sims, -np.inf)

        top_idx = np.argsort(-sims)[:top_k]

        results = []
        for idx in top_idx:
            if sims[idx] == -np.inf:
                break
            rid = self.meta[idx]["_id"]
            record = records_by_id.get(rid)
            if record is not None:
                results.append((record, float(sims[idx])))
        return results
