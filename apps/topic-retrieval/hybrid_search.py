"""키워드 검색 + 임베딩 검색 결과를 RRF(Reciprocal Rank Fusion)로 합친다.

한쪽에서만 찾았다고 그게 최선이라는 보장이 없어서, 둘 다 돌리고 순위를 합산하는
방식을 쓴다. score(d) = sum(1 / (k + rank)) — k=60은 RRF 논문에서 흔히 쓰는 값.
"""
from keyword_search import keyword_search
from embedding_search import EmbeddingIndex

RRF_K = 60


def reciprocal_rank_fusion(ranked_lists, k=RRF_K):
    """ranked_lists: [[(record, score, ...), ...], ...] — 각 리스트는 이미 순위대로 정렬됨.
    반환: [(record, rrf_score), ...] rrf_score 내림차순."""
    scores = {}
    records_by_id = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked):
            record = item[0]
            rid = record["_id"]
            records_by_id[rid] = record
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank + 1)

    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [(records_by_id[rid], score) for rid, score in ordered]


def hybrid_search(query, records, embedding_index: EmbeddingIndex, top_k=20):
    """records: 이미 학년/과목으로 필터링된 achievement_standard 레코드 리스트."""
    records_by_id = {r["_id"]: r for r in records}
    allowed_ids = set(records_by_id.keys())

    kw_results = keyword_search(query, records, top_k=top_k)
    emb_results = embedding_index.search(query, records_by_id, top_k=top_k, allowed_ids=allowed_ids)

    fused = reciprocal_rank_fusion([kw_results, emb_results])
    return fused[:top_k]
