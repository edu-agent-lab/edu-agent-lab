"""골든셋을 돌려 검색 품질을 숫자로 낸다.

기본은 fixtures/pages.json 스냅샷을 읽어 오프라인으로 동작한다.
튜닝하며 수십 번 돌릴 것이라 매번 Notion에 붙지 않는 편이 낫다.

    python eval.py              # 스냅샷으로 평가
    python eval.py --live       # Notion에서 직접 읽어 평가
    python eval.py --refresh    # 스냅샷을 다시 뜨고 평가
    python eval.py --case topic-01   # 한 케이스만
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from mcp_client import NotionPage, fetch_all_pages
from query_classifier import QueryFilters, QueryIntent, QueryType, classify_query
from search import search

APP_DIR = Path(__file__).parent
FIXTURE = APP_DIR / "fixtures" / "pages.json"
GOLDEN_SET = APP_DIR.parent.parent / "docs" / "notion-search" / "golden-set.jsonl"


# --- 데이터 --------------------------------------------------------------


def save_fixture(pages: list[NotionPage]) -> None:
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(
        json.dumps([p.__dict__ for p in pages], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_pages(*, live: bool = False, refresh: bool = False) -> list[NotionPage]:
    if refresh or live or not FIXTURE.exists():
        pages = fetch_all_pages()
        if refresh or not FIXTURE.exists():
            save_fixture(pages)
        return pages
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [NotionPage(**row) for row in raw]


def load_cases() -> list[dict]:
    lines = GOLDEN_SET.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def to_intent(spec: dict) -> QueryIntent:
    """골든셋의 정답 intent를 QueryIntent로 옮긴다.

    classify_query()가 완성되면 이 값이 분류기 정답지 역할도 하게 된다.
    """
    filters = spec.get("filters") or {}
    return QueryIntent(
        query_type=QueryType(spec["query_type"]),
        keyword=spec.get("keyword"),
        filters=QueryFilters(
            grade=filters.get("grade"),
            subject=filters.get("subject"),
            date_from=filters.get("date_from"),
            date_to=filters.get("date_to"),
        ),
    )


# --- 채점 ----------------------------------------------------------------


@dataclass
class Result:
    case_id: str
    query: str
    expect: list[str]
    got: list[str]
    noise: list[str]
    recall: float
    precision: float
    top_ok: bool | None
    type_ok: bool | None = None  # --classify 모드에서만 채워진다

    @property
    def passed(self) -> bool:
        return (
            self.recall == 1.0
            and self.precision == 1.0
            and not self.noise
            and self.top_ok is not False
        )


def score(case: dict, got_titles: list[str]) -> Result:
    expect = case["expect"]
    must_not = case.get("must_not", [])

    hit = [t for t in expect if t in got_titles]
    noise = [t for t in must_not if t in got_titles]

    # 0건이 정답인 케이스는 결과도 0건이어야 만점이다.
    recall = len(hit) / len(expect) if expect else (1.0 if not got_titles else 1.0)
    precision = (
        len(hit) / len(got_titles) if got_titles else (1.0 if not expect else 0.0)
    )

    top_ok = None
    if "expect_top" in case:
        top_ok = bool(got_titles) and got_titles[0] == case["expect_top"]

    return Result(
        case_id=case["id"],
        query=case["query"],
        expect=expect,
        got=got_titles,
        noise=noise,
        recall=recall,
        precision=precision,
        top_ok=top_ok,
    )


def run(
    pages: list[NotionPage], cases: list[dict], *, use_classifier: bool = False
) -> list[Result]:
    """골든셋을 돌린다.

    기본은 골든셋에 적힌 정답 intent로 검색만 채점한다. use_classifier면
    classify_query()가 만든 intent를 쓰므로 분류기까지 포함한 end-to-end 점수가 된다.
    """
    known_titles = [p.title for p in pages]

    results = []
    for case in cases:
        golden = to_intent(case["intent"])
        type_ok = None
        if use_classifier:
            intent = classify_query(case["query"], known_titles=known_titles)
            type_ok = intent.query_type is golden.query_type
        else:
            intent = golden

        hits = search(intent, pages)
        result = score(case, [m.title for m in hits])
        result.type_ok = type_ok
        results.append(result)
    return results


# --- 출력 ----------------------------------------------------------------


def report(results: list[Result], *, verbose: bool) -> None:
    width = 78
    print("=" * width)
    print(f"{'케이스':12} {'재현율':>7} {'정확도':>7} {'노이즈':>7}  {'질의'}")
    print("-" * width)

    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        flags = []
        if r.top_ok is not None:
            flags.append("1위 OK" if r.top_ok else "1위 틀림")
        if r.type_ok is not None and not r.type_ok:
            flags.append("유형 틀림")
        tail = ("  " + " · ".join(flags)) if flags else ""
        print(
            f"{r.case_id:12} {r.recall:7.2f} {r.precision:7.2f} "
            f"{len(r.noise):7}  {r.query[:30]:32} {mark}{tail}"
        )
        if verbose and not r.passed:
            missing = [t for t in r.expect if t not in r.got]
            extra = [t for t in r.got if t not in r.expect]
            if missing:
                print(f"{'':12}   놓침: {', '.join(missing)}")
            if extra:
                print(f"{'':12}   군더더기: {', '.join(extra)}")
            if r.noise:
                print(f"{'':12}   노이즈: {', '.join(r.noise)}")

    print("-" * width)
    n = len(results)
    passed = sum(r.passed for r in results)
    print(
        f"{'전체':12} {sum(r.recall for r in results) / n:7.2f} "
        f"{sum(r.precision for r in results) / n:7.2f} "
        f"{sum(len(r.noise) for r in results):7}  "
        f"{passed}/{n} 통과"
    )
    typed = [r for r in results if r.type_ok is not None]
    if typed:
        ok = sum(r.type_ok for r in typed)
        print(f"{'':12} {'':7} {'':7} {'':7}  분류기 유형 정확도 {ok}/{len(typed)}")
    print("=" * width)


def main() -> None:
    parser = argparse.ArgumentParser(description="골든셋 평가")
    parser.add_argument("--live", action="store_true", help="Notion에서 직접 읽기")
    parser.add_argument("--refresh", action="store_true", help="스냅샷 다시 뜨기")
    parser.add_argument("--case", help="특정 케이스 id만 실행")
    parser.add_argument(
        "--classify",
        action="store_true",
        help="classify_query()를 태워 end-to-end 채점 (LLM 호출 발생)",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="상세 출력 끄기")
    args = parser.parse_args()

    pages = load_pages(live=args.live, refresh=args.refresh)
    cases = load_cases()
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            raise SystemExit(f"케이스를 찾을 수 없습니다: {args.case}")

    source = "Notion 실시간" if (args.live or args.refresh) else "스냅샷"
    mode = "분류기 포함" if args.classify else "검색만 (골든셋 intent 사용)"
    print(f"\n데이터 {len(pages)}건 ({source}) · 케이스 {len(cases)}개 · {mode}\n")

    report(
        run(pages, cases, use_classifier=args.classify),
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    main()
