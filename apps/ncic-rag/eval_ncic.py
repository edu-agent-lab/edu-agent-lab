"""골든셋으로 검색 품질을 숫자로 낸다.

    python eval_ncic.py                          # v2 · hybrid
    python eval_ncic.py --mode dense
    python eval_ncic.py --compare                # mode 3종을 한 표로
    python eval_ncic.py --case topic-01 -v       # 한 케이스 상세

--mode bm25는 vecs.npy 없이도 돌아간다(모델 로드 없음).

지표는 apps/notion-search/eval.py의 재현율/노이즈를 그대로 쓰고 Top-1/Top-3를 더했다.
전략 문서의 평가 항목(Top-1, Top-3, 학년/과목 적합성)에 맞춘 것이다.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from retrieve import Index

GOLDEN_SET = Path(__file__).parent.parent.parent / "docs" / "ncic-rag" / "golden-set.jsonl"

# 검색은 Top-10까지 받아 Top-1/3/5/10을 한 번에 채점한다. 정답이 6건인 케이스
# (lexical-03)가 있어 5로는 재현율 만점이 불가능하다.
TOP_K = 10


def load_cases() -> list[dict]:
    return [
        json.loads(line)
        for line in GOLDEN_SET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def key_of(row: dict) -> str:
    """채점용 식별자.

    성취기준은 code로 유일하다. 나머지 doc_type은 code가 없는데, seq는 NCIC
    **페이지** id라서 한 seq에 최대 87개 레코드가 달린다(성격/목표가 같은 seq).
    그래서 seq에 하위 구분 필드를 붙여야 유일해진다 - 실측으로 4,075건 전부 유일.
    """
    if row.get("code"):
        return row["code"]
    tail = row.get("section") or "/".join(
        str(row[f]) for f in ("top", "sub") if row.get(f)
    )
    return f"seq:{row['seq']}#{tail}" if tail else f"seq:{row['seq']}"


@dataclass
class Result:
    case_id: str
    kind: str
    query: str
    expect: list[str]
    got: list[str]
    noise: list[str]
    top1: bool | None      # expect_top이 1위인가 (없으면 None)
    recall3: float
    recall10: float
    meta_ok: float         # Top-5가 요청한 학교급/과목 조건에 맞는 비율

    @property
    def passed(self) -> bool:
        return (
            self.recall10 == 1.0
            and not self.noise
            and self.top1 is not False
            and self.meta_ok == 1.0
        )


def score(case: dict, rows: list[dict]) -> Result:
    got = [key_of(r) for r in rows]
    expect = case.get("expect", []) + case.get("expect_key", [])
    must_not = case.get("must_not", [])

    def recall(n: int) -> float:
        if not expect:
            # 0건이 정답인 케이스: 뭐라도 나오면 0점.
            return 1.0 if not got else 0.0
        return sum(1 for e in expect if e in got[:n]) / len(expect)

    top1 = None
    if "expect_top" in case:
        top1 = bool(got) and got[0] == case["expect_top"]

    # 학교급·과목 적합성: 필터를 건 케이스에서 상위 5건이 조건을 지키는지.
    # 필터로 이미 걸러내므로 정상이면 1.0이고, 0.x면 필터가 새고 있다는 뜻이다.
    f = {k: v for k, v in (case.get("filters") or {}).items() if k != "doc_type"}
    top5 = rows[:5]
    if f and top5:
        meta_ok = sum(
            all(str(v) in str(r.get(k) or "") for k, v in f.items()) for r in top5
        ) / len(top5)
    else:
        meta_ok = 1.0

    return Result(
        case_id=case["id"],
        kind=case["kind"],
        query=case["query"],
        expect=expect,
        got=got,
        noise=[m for m in must_not if m in got],
        top1=top1,
        recall3=recall(3),
        recall10=recall(TOP_K),
        meta_ok=meta_ok,
    )


def run(index: Index, cases: list[dict], mode: str) -> list[Result]:
    results = []
    for case in cases:
        f = case.get("filters") or {}
        hits = index.search(
            case["query"],
            mode=mode,
            top_k=TOP_K,
            doc_type=f.get("doc_type"),
            school_level=f.get("school_level"),
            subject=f.get("subject"),
            course=f.get("course"),
        )
        results.append(score(case, [row for row, _ in hits]))
    return results


def report(results: list[Result], *, verbose: bool) -> None:
    width = 86
    print("=" * width)
    print(f"{'케이스':12} {'유형':9} {'Top1':>5} {'R@3':>6} {'R@10':>6} {'메타':>6} {'노이즈':>6}  질의")
    print("-" * width)
    for r in results:
        t1 = "-" if r.top1 is None else ("OK" if r.top1 else "X")
        mark = "PASS" if r.passed else "FAIL"
        print(
            f"{r.case_id:12} {r.kind:9} {t1:>5} {r.recall3:6.2f} {r.recall10:6.2f} "
            f"{r.meta_ok:6.2f} {len(r.noise):6}  {r.query[:28]:30} {mark}"
        )
        if verbose and not r.passed:
            missing = [e for e in r.expect if e not in r.got]
            if missing:
                print(f"{'':12}   놓침: {', '.join(missing)}")
            if r.noise:
                print(f"{'':12}   노이즈: {', '.join(r.noise)}")
            print(f"{'':12}   결과: {', '.join(r.got[:6])}")
    print("-" * width)

    n = len(results)
    scored = [r for r in results if r.top1 is not None]
    print(
        f"{'전체':12} {'':9} "
        f"{sum(bool(r.top1) for r in scored)}/{len(scored):<3} "
        f"{sum(r.recall3 for r in results) / n:6.2f} "
        f"{sum(r.recall10 for r in results) / n:6.2f} "
        f"{sum(r.meta_ok for r in results) / n:6.2f} "
        f"{sum(len(r.noise) for r in results):6}  "
        f"{sum(r.passed for r in results)}/{n} 통과"
    )
    print("=" * width)


def compare(index: Index, cases: list[dict], modes: list[str]) -> None:
    """mode별 요약만 한 표로. Vector vs Hybrid 비교용."""
    print(f"\n{'mode':8} {'Top1':>8} {'R@3':>7} {'R@10':>7} {'노이즈':>7} {'통과':>8}")
    print("-" * 50)
    per_case: dict[str, dict[str, float]] = {}
    for mode in modes:
        rs = run(index, cases, mode)
        scored = [r for r in rs if r.top1 is not None]
        print(
            f"{mode:8} {sum(bool(r.top1) for r in scored)}/{len(scored):<6} "
            f"{sum(r.recall3 for r in rs) / len(rs):7.2f} "
            f"{sum(r.recall10 for r in rs) / len(rs):7.2f} "
            f"{sum(len(r.noise) for r in rs):7} "
            f"{sum(r.passed for r in rs)}/{len(rs):<6}"
        )
        for r in rs:
            per_case.setdefault(r.case_id, {})[mode] = r.recall10

    # mode에 따라 갈리는 케이스만 따로 보여준다 - 어떤 질의에서 dense/bm25가
    # 서로를 메우는지가 이 실험의 결론이 된다.
    print(f"\nmode별로 결과가 갈린 케이스 (R@10)")
    print("-" * 50)
    diff = {cid: v for cid, v in per_case.items() if len(set(v.values())) > 1}
    if not diff:
        print("  없음 - 세 방식이 같은 결과")
    for cid, v in diff.items():
        print(f"  {cid:12} " + "  ".join(f"{m}={v[m]:.2f}" for m in modes))
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="NCIC 검색 평가")
    parser.add_argument("--mode", default="hybrid", choices=["dense", "bm25", "hybrid"])
    parser.add_argument("--variant", default="v2", choices=["v1", "v2", "v3"])
    parser.add_argument("--vecs", default=None)
    parser.add_argument("--compare", action="store_true", help="mode 3종 비교")
    parser.add_argument("--case", help="케이스 id 하나만")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    cases = load_cases()
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            raise SystemExit(f"케이스를 찾을 수 없습니다: {args.case}")

    from dataset import VECS

    index = Index(args.variant, args.vecs or VECS)
    print(f"\n케이스 {len(cases)}개 · variant={args.variant}")

    if args.compare:
        compare(index, cases, ["bm25", "dense", "hybrid"])
    else:
        print(f"mode={args.mode}\n")
        report(run(index, cases, args.mode), verbose=args.verbose)


if __name__ == "__main__":
    main()
