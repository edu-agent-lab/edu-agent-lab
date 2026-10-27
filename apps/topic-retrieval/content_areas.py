"""내용 체계 표에서 선택한 성취기준이 속한 영역만 골라낸다.

내용 체계 표는 과목의 모든 영역을 "(1) 지리 인식", "(2) 자연환경과 인간생활" ... 처럼
순서대로 나열한다. 중학교 사회는 11개 영역 10,759자다. 앞에서부터 글자 수로 자르면
앞 영역만 남는다 — "개발과 환경 보전" 수업(9사(지리)12-02)의 영역은 (4)번인데 3,453자에서
시작해서 2,500자 컷에 통째로 빠졌다.

## 성취기준 코드로는 바로 못 찾는다

성취기준의 area는 단원 단위고, 내용 체계 표의 영역은 초3~중3을 아우르는 큰 단위라
번호도 이름도 이어지지 않는다.

    성취기준  9사(지리)12  "지속가능한 세계와 글로컬 시민"   (지리 단원 12개 중 12번째)
    내용 체계 (4)         "지속가능한 세계"                (사회 전체 영역 11개 중 4번째)

그래서 두 단계로 찾는다:

1. **이름이 같으면 그 영역** — 국어 "읽기", 수학 "수와 연산", 영어 "이해"처럼 성취기준
   area와 표 제목이 같은 과목이 많다 (일반 교과 성취기준 1,755건 중 1,496건)
2. **아니면 내용 비교** — 성취기준 문장+area를 쿼리로, 표의 각 영역 블록(핵심 아이디어 +
   내용 요소)을 문서로 BM25를 매긴다

이름이 같은 1,496건을 정답으로 놓고 2번만 돌려보면 1,454건(97%)이 맞는다. 이름이 다른
나머지는 2번이 맡는다. 중학교 사회 지리처럼 단원 하나("아시아")의 성취기준이 위치는
"지리 인식", 문화·인구·산업은 "인문환경과 인간생활"로 갈리는데, 실제 내용이 그렇다.

## IDF는 전체 내용 체계 기준

한 과목의 영역은 2~11개뿐이다. 영어는 "이해"/"표현" 2개라 그 안에서 IDF를 계산하면
한쪽에만 있는 단어의 IDF가 0이 되어 모든 점수가 0이 된다. 그래서 IDF는 모든 내용 체계
표의 영역 블록 전체에서 계산하고, 점수는 해당 과목의 블록에만 매긴다. "탐구", "이해"
같은 교육과정 상투어도 전체 기준이라 자연스럽게 눌린다.
"""

from __future__ import annotations

import re
from functools import lru_cache

from rank_bm25 import BM25Okapi

from data_loader import load_records
from keyword_search import tokenize

_AREA_HEAD = re.compile(r"^\((\d+)\) (.+)$", re.M)


def split_areas(text: str) -> tuple[str, list[tuple[str, str]]]:
    """내용 체계 원문을 (머리말, [(영역명, 블록 원문), ...])으로 나눈다.

    영역 제목이 2개 미만이면 나눌 게 없어서 빈 리스트를 돌려준다 (통합교과·단일 영역
    과목은 표가 짧아 통째로 넣어도 된다).
    """
    heads = list(_AREA_HEAD.finditer(text))
    if len(heads) < 2:
        return text, []
    ends = [h.start() for h in heads[1:]] + [len(text)]
    blocks = [(h.group(2).strip(), text[h.start():end].strip()) for h, end in zip(heads, ends)]
    return text[: heads[0].start()].strip(), blocks


def _norm(name: str) -> str:
    """"이해(reception)"과 "이해", "사회⋅문화"와 "사회·문화"를 같게 본다."""
    return re.sub(r"\(.*?\)|[\s⋅·,]", "", name)


@lru_cache(maxsize=1)
def _corpus():
    """모든 내용 체계 표의 영역 블록으로 BM25를 만든다. {_id: 첫 블록 위치}도 같이."""
    tokens, offset = [], {}
    for r in load_records(doc_type="content_system"):
        _, blocks = split_areas(r["text"])
        offset[r["_id"]] = len(tokens)
        tokens += [tokenize(body) for _, body in blocks]
    return BM25Okapi(tokens), offset


def pick_area(blocks: list[tuple[str, str]], standard: dict, doc_id: int | None = None) -> int | None:
    """성취기준 하나가 속한 영역의 인덱스. 못 찾으면 None."""
    names = [_norm(name) for name, _ in blocks]
    area = _norm(standard.get("area") or "")
    if area in names:
        return names.index(area)

    query = tokenize(f"{standard['content']} {standard.get('area') or ''}")
    bm25, offset = _corpus()
    if doc_id in offset:
        start = offset[doc_id]
        scores = bm25.get_batch_scores(query, list(range(start, start + len(blocks))))
    else:
        # 데이터 파일 밖에서 온 문서(테스트 등). 블록끼리만 비교한다.
        scores = BM25Okapi([tokenize(body) for _, body in blocks]).get_scores(query)
    best = max(range(len(blocks)), key=lambda i: scores[i])
    return best if scores[best] > 0 else None


def relevant_areas(doc: dict, standards: list[dict]) -> str | None:
    """선택한 성취기준들이 속한 영역만 남긴 내용 체계 원문. 못 고르면 None.

    성취기준 여러 개가 다른 영역이면 해당 영역을 모두, 원래 순서대로 넣는다.
    """
    head, blocks = split_areas(doc["text"])
    if not blocks or not standards:
        return None
    picked = {pick_area(blocks, s, doc.get("_id")) for s in standards} - {None}
    if not picked:
        return None
    kept = [blocks[i][1] for i in sorted(picked)]
    skipped = len(blocks) - len(picked)
    note = f"(이 수업과 관련된 영역만 발췌 — 나머지 {skipped}개 영역 생략)"
    return "\n\n".join([head, note, *kept])
