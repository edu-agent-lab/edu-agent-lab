"""QueryIntent + 전체 페이지 -> 정렬된 검색 결과.

mcp_client가 가져온 원본을 여기서 가공한다. 데이터셋 실측에서 나온 제약이 세 가지 있고,
이 모듈은 사실상 그 세 가지를 메우기 위해 존재한다.

1. 속성이 절반쯤 비어 있다 (과목 7/14, 학년 6/14, 날짜 3/14 누락).
   -> 속성 -> 본문 -> 제목 순으로 폴백해 값을 채운다.
2. 같은 과목이 표기가 다르다 (`공통 영어1` vs `공통영어1`).
   -> 공백/숫자를 지운 뒤 대표 키로 정규화해서 비교한다.
3. 같은 주제가 요청서/완성물 짝으로 들어 있다 (4-3, 11-14, 10-2).
   -> 거르지 않고 완성물을 위로 올리기만 한다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from mcp_client import (
    NotionPage,
    date_of,
    grade_of,
    semester_of,
    subjects_of,
    title_of,
)
from query_classifier import QueryIntent, QueryType

# 제목이 이 정도로 닮으면 같은 페이지를 가리킨 것으로 본다.
TITLE_MATCH_THRESHOLD = 0.6

# 키워드가 본문 어딘가에 스치기만 해도 걸리면 결과가 급격히 늘어난다
# ("토론" 하나에 14건 중 9건). 제목/자료유형/본문 메타 중 하나에는 걸려야
# 통과하도록 아래 점수를 최소선으로 둔다.
MIN_KEYWORD_SCORE = 3.0

# 과목 대표 키. 순서가 중요하다 - `한국사`를 `사회`보다 먼저 봐야
# "한국사1"이 사회로 빨려 들어가지 않는다.
SUBJECT_KEYS = ["한국사", "수학", "국어", "영어", "사회", "과학", "정보"]

# 본문 `- 자료 유형: 퀴즈`에서 얻는 값. 없으면 제목/본문에서 추론한다.
MATERIAL_TYPES = ["퀴즈", "프로젝트", "토론", "교안", "계획안", "활동지"]

# 이 필드가 있으면 완성된 자료가 아니라 "이런 걸 만들어줘" 요청서다.
REQUEST_MARKER = "원하는 활동 자료 유형"

# 본문 앞머리의 `- 키: 값` 라인. 섹션 제목은 페이지마다 제각각이라
# (`# 자료 개요`, `## 개념 설명`, `### 과목 정보`, 아예 없는 경우까지)
# 헤딩에 기대지 않고 이 패턴만 훑는다.
_FIELD_RE = re.compile(r"^-\s*([^:：]+?)\s*[:：]\s*(.+)$")


def _normalize(text: str) -> str:
    """공백과 숫자를 지운다. `공통 영어1` / `공통영어1` -> `공통영어`."""
    return re.sub(r"[\s\d]", "", text)


def _subject_key(text: str) -> str | None:
    """임의의 과목 표기를 대표 키로 바꾼다. 못 찾으면 None."""
    normalized = _normalize(text)
    for key in SUBJECT_KEYS:
        if key in normalized:
            return key
    return None


def _body_fields(markdown: str) -> dict[str, str]:
    """본문 첫 섹션의 `- 키: 값` 라인을 수집한다."""
    fields: dict[str, str] = {}
    for raw in markdown.split("\n"):
        line = raw.strip()
        if line.startswith("#") and fields:
            break  # 첫 섹션이 끝나면 중단
        matched = _FIELD_RE.match(line)
        if matched:
            fields[matched.group(1).strip()] = matched.group(2).strip()
    return fields


@dataclass
class PageMeta:
    """속성/본문/제목을 합쳐 검색에 바로 쓸 수 있게 만든 형태."""

    page: NotionPage
    title: str
    subject_keys: list[str] = field(default_factory=list)
    grade: str | None = None
    date: str | None = None
    semester: str | None = None
    material_type: str | None = None
    is_request: bool = False
    body_fields: dict[str, str] = field(default_factory=dict)

    @property
    def searchable(self) -> str:
        """키워드 매칭 대상. 제목 + 본문 메타 + 본문 전체."""
        return "\n".join(
            [self.title, *self.body_fields.values(), self.page.content]
        )


def build_meta(page: NotionPage) -> PageMeta:
    props = page.properties
    fields = _body_fields(page.content)
    title = title_of(props) or page.title

    # 과목: 속성 -> 본문 -> 제목 순으로 찾는다. 하나라도 걸리면 멈추지 않고
    # 전부 모은다 (한 페이지가 여러 과목일 수 있으므로).
    keys: list[str] = []
    for source in (*subjects_of(props), fields.get("과목", ""), title):
        key = _subject_key(source) if source else None
        if key and key not in keys:
            keys.append(key)

    # 학년: 속성이 없으면 본문 `대상`에서. 실측상 둘 다 없는 페이지가 6건 있어
    # 어차피 절반은 비게 된다.
    grade = grade_of(props)
    if not grade and "대상" in fields:
        matched = re.search(r"(고|중|초)등학교\s*(\d)학년", fields["대상"])
        if matched:
            grade = f"{matched.group(1)}{matched.group(2)}"

    # 자료 유형: 본문 필드가 우선, 없으면 제목에서 추론.
    material = fields.get("자료 유형")
    if not material:
        material = next((t for t in MATERIAL_TYPES if t in title), None)
    if not material and {"찬성", "반대"} & set(fields):
        material = "토론"  # 찬반 쟁점이 적혀 있으면 토론 자료다

    return PageMeta(
        page=page,
        title=title,
        subject_keys=keys,
        grade=grade,
        date=date_of(props),
        semester=semester_of(props),
        material_type=material,
        is_request=REQUEST_MARKER in fields,
        body_fields=fields,
    )


def _passes_filters(meta: PageMeta, intent: QueryIntent) -> bool:
    f = intent.filters

    if f.subject:
        wanted = _subject_key(f.subject)
        # 데이터셋에 없는 과목("체육")은 대표 키로 변환되지 않는다. 이때 필터를
        # 통과시키면 조건이 통째로 무시돼 전체가 결과로 나오므로 전부 제외한다.
        if wanted is None or wanted not in meta.subject_keys:
            return False

    if f.grade and _normalize(f.grade) != _normalize(meta.grade or ""):
        return False

    # 날짜는 폴백하지 않는다. 제목이나 본문으로 작성일을 추론할 수 없으므로,
    # 날짜 속성이 빈 3건은 날짜 조건이 걸리면 빠지는 게 맞다.
    if f.date_from or f.date_to:
        if not meta.date:
            return False
        if f.date_from and meta.date < f.date_from:
            return False
        if f.date_to and meta.date > f.date_to:
            return False

    return True


def _score(meta: PageMeta, intent: QueryIntent) -> float:
    """높을수록 상위. 0 이하는 결과에서 제외한다."""
    if intent.query_type is QueryType.TITLE and intent.keyword:
        score = SequenceMatcher(None, intent.keyword, meta.title).ratio()
        return score if score >= TITLE_MATCH_THRESHOLD else 0.0

    if not intent.keyword:
        # ATTRIBUTE 질의: 필터만 통과하면 되므로 전부 동점.
        # 날짜 있는 자료를 최신순으로 보여주는 게 자연스럽다.
        return 1.0

    keyword = intent.keyword.strip()
    # 낱말 단위로 채점한다. "토론 수업"처럼 여러 단어가 들어오면 전체 문자열로는
    # 어디에도 안 걸려 전멸하기 때문이다.
    words = [w for w in re.split(r"\s+", keyword) if len(w) >= 2] or [keyword]
    score = 0.0

    # 제목: 통째로 들어가면 만점, 낱말만 걸리면 걸린 비율만큼.
    if keyword in meta.title or _normalize(keyword) in _normalize(meta.title):
        score += 3.0
    else:
        hits = sum(
            1
            for w in words
            if w in meta.title or _normalize(w) in _normalize(meta.title)
        )
        score += 3.0 * hits / len(words)

    # 자료 유형은 한 낱말이라 "토론 수업"의 "토론"만 맞아도 인정한다.
    if meta.material_type and any(w in meta.material_type for w in words):
        score += 2.0

    # 본문 앞머리의 `- 주제: ...`는 사실상 부제목이라 본문 전체보다 신호가 훨씬 강하다.
    # 요청서 페이지는 제목이 뭉뚱그려져 있고("공통 수학 학습자료 생성 요청") 실제 주제가
    # 여기에만 적혀 있어서, 이 배점이 낮으면 통째로 누락된다.
    meta_hits = sum(
        1 for w in words if any(w in v for v in meta.body_fields.values())
    )
    score += 2.5 * meta_hits / len(words)

    hits = sum(1 for w in words if w in meta.page.content)
    score += 1.0 * hits / len(words)

    return score if score >= MIN_KEYWORD_SCORE else 0.0


def describe_results(metas: list[PageMeta], intent: QueryIntent) -> str:
    """와이어프레임의 "검색 결과 요약" 영역에 넣을 한 문단을 만든다.

    LLM을 부르지 않는다. 필요한 정보(자료 유형, 과목, 날짜, 요청서 여부)가 이미
    PageMeta에 다 있고, 이 영역은 화면 맨 위라 결과가 나오자마자 보여야 하기 때문이다.
    페이지별 요약을 기다렸다가 만들면 맨 위 문장이 가장 늦게 뜬다.
    """
    if not metas:
        return "검색 결과가 없습니다. 다른 검색어로 시도해보세요."

    scope_words = [
        word
        for word in (
            intent.filters.grade,
            intent.filters.subject,
            f"'{intent.keyword}' 관련" if intent.keyword else None,
        )
        if word
    ]
    scope = (" ".join(scope_words) + " 자료") if scope_words else "자료"

    sentences = [f"{scope} {len(metas)}건을 찾았습니다."]

    # 자료 유형이 여러 종류면 분포를, 한 종류뿐이면(이미 검색어에 드러난 경우가 많다)
    # 대신 과목 분포를 알려준다. 같은 말을 두 번 하지 않기 위한 분기다.
    types = Counter(m.material_type for m in metas if m.material_type)
    if len(types) > 1:
        sentences.append(
            ", ".join(f"{name} {count}건" for name, count in types.most_common())
            + "입니다."
        )
    else:
        subjects = sorted({key for m in metas for key in m.subject_keys})
        if len(subjects) > 1:
            sentences.append("·".join(subjects) + " 과목에 걸쳐 있습니다.")

    requests = sum(m.is_request for m in metas)
    if requests == len(metas):
        sentences.append("완성된 자료가 아니라 자료 생성 요청서입니다.")
    elif requests:
        sentences.append(f"이 중 {requests}건은 자료 생성 요청서입니다.")

    return " ".join(sentences)


def search(intent: QueryIntent, pages: list[NotionPage]) -> list[PageMeta]:
    """필터를 통과하고 키워드에 걸리는 페이지를 점수순으로 반환한다."""
    metas = [build_meta(p) for p in pages]
    candidates = [m for m in metas if _passes_filters(m, intent)]

    scored = [(m, _score(m, intent)) for m in candidates]
    scored = [(m, s) for m, s in scored if s > 0]

    # 정렬 기준: 점수 -> 완성물 우선 -> 최신순.
    # 요청서를 거르지 않는 이유는, 요청서만 있고 완성물이 없는 주제도 있어서다.
    scored.sort(
        key=lambda x: (x[1], not x[0].is_request, x[0].date or ""),
        reverse=True,
    )

    if intent.query_type is QueryType.TITLE:
        return [m for m, _ in scored[:1]]
    return [m for m, _ in scored]
