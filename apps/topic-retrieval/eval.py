#!/usr/bin/env python3
"""골든셋(docs/topic-retrieval/golden-set.jsonl) 채점.

지표는 두 구현의 것을 합쳤다 — MRR(순위 평균)과 Top-1(1위 정확도)은 보완적이다.

    recall@3/@10  정답이 상위 N에 들어왔나
    MRR           정답이 몇 위였나 (1위=1.0, 2위=0.5, 5위=0.2)
    Top-1         expect_top이 1위인가 (지정된 케이스만)
    메타          상위 5건이 요청한 school_level/subject를 지키나 (필터 누수 감지)
    노이즈         must_not이 섞였나

검색 구조를 단계별로 떼어서 비교한다:
    filter  슬롯 필터만 (범위 확인용. 랭킹 없음)
    bm25    슬롯 필터 + BM25
    embed   슬롯 필터 + 임베딩
    hybrid  슬롯 필터 + 둘 다 (기본)

    python eval.py                        # hybrid
    python eval.py --compare              # 단계별 + 결합 방식 한 표로
    python eval.py --stage bm25 --case topic-10 -v
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

# 정답이 여러 건인 케이스가 있어 Top-10까지 받아 한 번에 채점한다.
TOP_K = 10


def load_golden(path=GOLDEN_PATH):
    cases = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            q = json.loads(line)
            if q["id"] == "example":       # 형식 참고용
                continue
            if q.get("deferred"):           # 이번 범위 밖 (서술 문서 인덱스 미구현)
                continue
            cases.append(q)
    return cases


def run_stage(stage, topic, scoped, top_k, fusion="weighted"):
    """반환: [(record, score), ...] score 내림차순."""
    if stage == "filter":
        # 랭킹 없이 범위 안을 그대로. recall/mrr은 의미가 없고(범위 안이면 전부 1위),
        # 0건이 정답인 케이스에서 범위 자체가 얼마나 넓은지 보는 용도다.
        return [(r, 1.0) for r in scoped[:top_k]]
    if stage == "bm25":
        return [(r, s) for r, s, _ in keyword_search(topic, scoped, top_k=top_k)]
    if stage == "embed":
        from embedding_search import EmbeddingIndex

        records_by_id = {r["_id"]: r for r in scoped}
        return EmbeddingIndex().search(
            topic, records_by_id, top_k=top_k, allowed_ids=set(records_by_id)
        )
    if stage == "hybrid":
        from embedding_search import EmbeddingIndex
        from hybrid_search import hybrid_search

        return hybrid_search(topic, scoped, EmbeddingIndex(), top_k=top_k, fusion=fusion)
    raise ValueError(f"알 수 없는 stage: {stage}")


def score_case(case, ranked, top_k):
    codes = [r.get("code") for r, _ in ranked[:top_k]]
    expect = case.get("expect") or []
    must_not = case.get("must_not") or []

    noise = [m for m in must_not if m in codes]

    # 요청한 조건을 상위 5건이 지키는지. 필터가 새면 1.00 아래로 떨어진다.
    slots = {k: case[k] for k in ("school_level", "subject") if case.get(k)}
    top5 = [r for r, _ in ranked[:5]]
    if slots and top5:
        meta_ok = sum(
            all(r.get(k) == v for k, v in slots.items()) for r in top5
        ) / len(top5)
    else:
        meta_ok = 1.0

    if not expect:
        # 0건이 정답. 결과가 비어 있어야 이상적이고, 있으면 전부 노이즈로 본다.
        return {
            "recall3": None, "recall10": None, "mrr": None,
            "top1": None, "meta_ok": meta_ok,
            "noise": len(codes), "missing": [],
            "pass": len(codes) == 0,
        }

    def recall(n):
        return sum(1 for e in expect if e in codes[:n]) / len(expect)

    hit_ranks = [codes.index(e) + 1 for e in expect if e in codes]
    mrr = 1.0 / min(hit_ranks) if hit_ranks else 0.0

    top1 = None
    if case.get("expect_top"):
        top1 = bool(codes) and codes[0] == case["expect_top"]

    r10 = recall(TOP_K)
    return {
        "recall3": recall(3), "recall10": r10, "mrr": mrr,
        "top1": top1, "meta_ok": meta_ok,
        "noise": len(noise), "missing": [e for e in expect if e not in codes],
        "pass": r10 == 1.0 and not noise and top1 is not False and meta_ok == 1.0,
    }


def evaluate(cases, all_records, stage, top_k, fusion="weighted"):
    out = []
    for case in cases:
        scoped = filter_by_slots(
            all_records,
            school_level=case.get("school_level"),
            subject=case.get("subject"),
            course=case.get("course"),
        )
        ranked = run_stage(stage, case["topic"], scoped, top_k, fusion)
        out.append((case, score_case(case, ranked, top_k), len(scoped)))
    return out


def _avg(key, src):
    return (sum(r[key] for r in src) / len(src)) if src else 0.0


def summarize(results):
    n = len(results)
    rs = [r for _, r, _ in results]
    scored = [r for r in rs if r["recall10"] is not None]
    typed = [r for r in rs if r["top1"] is not None]
    t1 = f"{sum(bool(r['top1']) for r in typed)}/{len(typed)}" if typed else "-"
    return (
        f"{t1:>7} {_avg('recall3', scored):7.2f} {_avg('recall10', scored):7.2f} "
        f"{_avg('mrr', scored):7.2f} {_avg('meta_ok', rs):7.2f} "
        f"{sum(r['noise'] for r in rs):7} {sum(r['pass'] for r in rs)}/{n}"
    )


HEAD = f"{'Top1':>7} {'R@3':>7} {'R@10':>7} {'MRR':>7} {'메타':>7} {'노이즈':>7} 통과"


def report(results, *, verbose):
    print("=" * 102)
    print(
        f"{'id':12} {'유형':9} {'후보':>5} {'Top1':>5} {'R@3':>6} {'R@10':>6} "
        f"{'MRR':>6} {'메타':>6} {'노이즈':>6}  주제"
    )
    print("-" * 102)
    for case, r, n_scoped in results:
        t1 = "-" if r["top1"] is None else ("OK" if r["top1"] else "X")
        fmt = lambda v: "-" if v is None else f"{v:.2f}"
        mark = "PASS" if r["pass"] else "FAIL"
        print(
            f"{case['id']:12} {case.get('kind', 'topic'):9} {n_scoped:5} {t1:>5} "
            f"{fmt(r['recall3']):>6} {fmt(r['recall10']):>6} {fmt(r['mrr']):>6} "
            f"{r['meta_ok']:6.2f} {r['noise']:6}  {case['topic'][:30]:32} {mark}"
        )
        if verbose and not r["pass"]:
            if r["missing"]:
                print(f"{'':12}   놓침: {', '.join(r['missing'])}")
            if r["noise"]:
                print(f"{'':12}   노이즈 {r['noise']}건")
    print("-" * 102)
    print(f"{'전체':12} {'':9} {'':5} {summarize(results)}")
    print("=" * 102)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--stage", choices=["filter", "bm25", "embed", "hybrid"], default="hybrid"
    )
    ap.add_argument("--fusion", default="weighted", choices=["weighted", "rrf"])
    ap.add_argument("--compare", action="store_true", help="단계별 + 결합 방식 비교")
    ap.add_argument("--case", default=None)
    ap.add_argument("--top_k", type=int, default=TOP_K)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    cases = load_golden()
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            raise SystemExit(f"케이스 없음: {args.case}")

    all_records = load_records(doc_type="achievement_standard")
    print(f"\n케이스 {len(cases)}개 · 성취기준 {len(all_records)}건 · top_k={args.top_k}")

    if args.compare:
        print(f"\n{'stage':10} {'결합':10} {HEAD}")
        print("-" * 74)
        for stage in ("filter", "bm25", "embed", "hybrid"):
            fusions = ("weighted", "rrf") if stage == "hybrid" else ("-",)
            for fu in fusions:
                rs = evaluate(
                    cases, all_records, stage, args.top_k,
                    fu if fu != "-" else "weighted",
                )
                print(f"{stage:10} {fu:10} {summarize(rs)}")
        print()
    else:
        print(f"stage={args.stage} · fusion={args.fusion}\n")
        report(
            evaluate(cases, all_records, args.stage, args.top_k, args.fusion),
            verbose=args.verbose,
        )


if __name__ == "__main__":
    main()
