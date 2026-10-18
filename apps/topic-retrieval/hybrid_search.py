"""키워드(BM25) + 임베딩(dense) 결과를 합쳐 최종 순위를 만든다.

**BM25가 주력, dense가 보조다.** 슬롯 필터로 후보가 16~121건까지 좁혀진 뒤에 검색하기
때문에 어휘 겹침만으로 대부분 풀린다. dense는 표현이 어긋날 때("환경 보전" vs 원문
"환경 보존")만 순위를 보정한다.

    score = bm25_정규화 + DENSE_WEIGHT * dense_코사인

**BM25가 0건이면 결과 없음으로 끝낸다** (게이트). 질의 단어가 후보 어디에도 없다는
뜻이고, dense는 코사인이 항상 양수라 이 판단을 못 한다. 실측으로 코사인에 전역
임계값을 두는 건 불가능했다 — 정답이 0건인 질의의 1위 코사인(0.569)이 정답이 있는
질의(0.497)보다 높다. BM25 게이트가 그 문제를 공짜로 해결한다.

골든셋 38건 실측 (docs/topic-retrieval/evaluation.md):

| 방식                        | Top-1 | R@3  | 노이즈 | 통과  |
|-----------------------------|-------|------|--------|-------|
| BM25 단독                   | 7/10  | 0.88 | 2      | 31/38 |
| BM25 주력 + dense 0.5       | 8/10  | 0.90 | 1      | 32/38 |
| dense 주력 + BM25 0.15      | 9/10  | 0.90 | 3      | 32/38 |
| 게이트 없는 hybrid          | 9/10  | 0.91 | 33     | 29/38 |

게이트 없는 쪽의 노이즈 33은 0건이 정답인 케이스 3건이 각각 10건을 반환해서다.

RRF는 쓰지 않는다. 순위만 쓰고 점수 크기를 버리기 때문에 dense와 BM25를 동등하게
취급하게 되고, 양쪽 골든셋에서 일관되게 나빴다 (22건: 8개 조합 전부 하위권,
19건: R@1 0.84~0.89 vs 가중합 0.89~0.95). 비교용으로만 남겨둔다.
"""
from embedding_search import EmbeddingIndex
from keyword_search import keyword_search

# BM25(후보군 내 최대값으로 0~1 정규화)에 더할 dense 비중.
#
# 골든셋 38건 스윕(BM25 주력): 0.0 -> 32/38, 0.3 -> 32, 0.5 -> 32, 1.0 -> 32.
# 통과 수는 평평하고 Top-1/MRR이 0.5에서 가장 좋다.
DENSE_WEIGHT = 0.5

RRF_K = 60


def reciprocal_rank_fusion(ranked_lists, k=RRF_K):
    """순위 기반 결합. 비교 실험용으로만 남겨둔 경로 (기본값은 가중합)."""
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


def weighted_fusion(kw_results, emb_results, dense_weight=DENSE_WEIGHT):
    """BM25를 기준선으로 두고 dense를 가산한다.

    한쪽에만 있는 레코드는 다른 쪽 점수를 0으로 본다 — top_k 밖이라는 뜻이고,
    그만큼 불리하게 두는 게 맞다.
    """
    bm_max = max((s for _, s, *_ in kw_results), default=0.0)

    records_by_id = {}
    bm = {}
    for record, score, *_ in kw_results:
        records_by_id[record["_id"]] = record
        bm[record["_id"]] = (score / bm_max) if bm_max > 0 else 0.0
    dense = {}
    for record, score in emb_results:
        records_by_id[record["_id"]] = record
        dense[record["_id"]] = score

    scores = {
        rid: bm.get(rid, 0.0) + dense_weight * dense.get(rid, 0.0)
        for rid in records_by_id
    }
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [(records_by_id[rid], score) for rid, score in ordered]


def hybrid_search(
    query,
    records,
    embedding_index: EmbeddingIndex,
    top_k=20,
    fusion="weighted",
    gate=True,
):
    """records: 이미 슬롯(학년/과목/코스)으로 필터링된 achievement_standard 리스트.

    gate=True면 BM25가 0건일 때 빈 결과를 돌려준다 ("관련 성취기준 없음").
    fusion: "weighted"(기본) | "rrf"(비교용)
    """
    records_by_id = {r["_id"]: r for r in records}
    allowed_ids = set(records_by_id.keys())

    kw_results = keyword_search(query, records, top_k=top_k)
    if gate and not kw_results:
        return []

    emb_results = embedding_index.search(
        query, records_by_id, top_k=top_k, allowed_ids=allowed_ids
    )

    if fusion == "rrf":
        fused = reciprocal_rank_fusion([kw_results, emb_results])
    else:
        fused = weighted_fusion(kw_results, emb_results)
    return fused[:top_k]
