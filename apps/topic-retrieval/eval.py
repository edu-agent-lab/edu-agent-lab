#!/usr/bin/env python3
"""골든셋(docs/topic-retrieval/golden-set.jsonl) 채점 스크립트.

검색 구조 4단계를 단계별로 떼어서 비교하려고 --stage를 둔다.
  filter  : 슬롯 필터만 (키워드/임베딩 없이 범위 안 전체를 그대로 반환 — 필터 자체 확인용)
  bm25    : 슬롯 필터 + BM25 키워드 검색
  embed   : 슬롯 필터 + 임베딩 검색 (로컬 모델. 최초 실행 시 다운로드, 느림)
  hybrid  : 슬롯 필터 + BM25 + 임베딩 RRF

사용:
    python eval.py --stage bm25
    python eval.py --stage bm25 --case topic-10
    python eval.py --stage filter --case topic-19
"""
import argparse
import json
import os

from data_loader import filter_by_slots, load_records
from keyword_search import keyword_search

GOLDEN_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "docs", "topic-retrieval", "golden-set.jsonl",
)

TOP_K = 10


def load_golden(path=GOLDEN_PATH):
    cases = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            q = json.loads(line)
            if q["id"] == "example":
                continue
            cases.append(q)
    return cases


def run_stage(stage, topic, scoped, top_k):
    """반환: [(record, score), ...] score 내림차순."""
    if stage == "filter":
        # 키워드 없이 범위 안 전체를 그대로 반환한다. recall/mrr은 의미가 없고
        # (범위 안이면 전부 1위), 노이즈 질의(expect=[])에서 범위 자체가 얼마나
        # 넓은지 보는 용도다.
        return [(r, 1.0) for r in scoped[:top_k]]
    if stage == "bm25":
        return [(r, s) for r, s, _ in keyword_search(topic, scoped, top_k=top_k)]
    if stage == "embed":
        from embedding_search import EmbeddingIndex
        records_by_id = {r["_id"]: r for r in scoped}
        index = EmbeddingIndex()
        return index.search(topic, records_by_id, top_k=top_k, allowed_ids=set(records_by_id))
    if stage == "hybrid":
        from embedding_search import EmbeddingIndex
        from hybrid_search import hybrid_search
        return hybrid_search(topic, scoped, EmbeddingIndex(), top_k=top_k)
    raise ValueError(f"알 수 없는 stage: {stage}")


def score_case(case, ranked, top_k):
    codes_ranked = [r["code"] for r, _ in ranked[:top_k]]
    expect = case["expect"]

    if not expect:
        # 무관 질의: 결과가 비어 있어야 이상적. 있으면 전부 노이즈로 본다.
        noise = len(codes_ranked)
        return {"recall": None, "mrr": None, "noise": noise, "pass": noise == 0}

    hit_ranks = [codes_ranked.index(c) + 1 for c in expect if c in codes_ranked]
    recall = len(hit_ranks) / len(expect)
    mrr = (1.0 / min(hit_ranks)) if hit_ranks else 0.0
    return {"recall": recall, "mrr": mrr, "noise": None, "pass": recall == 1.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["filter", "bm25", "embed", "hybrid"], default="bm25")
    ap.add_argument("--case", default=None, help="특정 id만 실행 (예: topic-10)")
    ap.add_argument("--top_k", type=int, default=TOP_K)
    args = ap.parse_args()

    cases = load_golden()
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            raise SystemExit(f"케이스 없음: {args.case}")

    all_records = load_records(doc_type="achievement_standard")

    print(f"stage={args.stage} · 케이스 {len(cases)}개 · top_k={args.top_k}")
    print("=" * 92)
    print(f"{'id':10} {'recall':>6} {'mrr':>6} {'noise':>6}  질의")
    print("-" * 92)

    recalls, mrrs, passed_n = [], [], 0
    for case in cases:
        scoped = filter_by_slots(
            all_records,
            school_level=case["school_level"],
            subject=case["subject"],
            course=case.get("course"),
        )
        ranked = run_stage(args.stage, case["topic"], scoped, args.top_k)
        result = score_case(case, ranked, args.top_k)

        status = "PASS" if result["pass"] else "FAIL"
        recall_s = "-" if result["recall"] is None else f"{result['recall']:.2f}"
        mrr_s = "-" if result["mrr"] is None else f"{result['mrr']:.2f}"
        noise_s = "-" if result["noise"] is None else str(result["noise"])
        print(f"{case['id']:10} {recall_s:>6} {mrr_s:>6} {noise_s:>6}  {case['topic']:28} {status}")

        if result["recall"] is not None:
            recalls.append(result["recall"])
            mrrs.append(result["mrr"])
        if result["pass"]:
            passed_n += 1

    print("-" * 92)
    avg_recall = sum(recalls) / len(recalls) if recalls else 0.0
    avg_mrr = sum(mrrs) / len(mrrs) if mrrs else 0.0
    print(f"평균 recall={avg_recall:.2f}  평균 mrr={avg_mrr:.2f}  통과 {passed_n}/{len(cases)}")


if __name__ == "__main__":
    main()
