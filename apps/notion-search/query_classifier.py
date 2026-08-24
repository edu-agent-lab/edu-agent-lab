"""자연어 질의 -> QueryIntent 변환.

판단 순서 (Day2 Step2 하이브리드를 데이터에 맞춰 조정):

1. 제목 매칭 - 데이터셋 제목 14개와 대조한다. 걸리면 LLM을 부르지 않는다.
   목록을 손에 쥐고 있으므로 이게 가장 정확하고 공짜다.
2. 규칙 기반 - 학년/과목이 그대로 등장하고 날짜 표현이 없으면 바로 판정한다.
   이때 속성 단어를 걷어낸 나머지를 keyword로 남긴다. "부등식 관련 수학 자료"에서
   "부등식"을 잃으면 수학 자료가 전부 나와버린다.
3. LLM - 날짜 표현이 섞였거나 속성 신호가 없는 나머지.
   LLM을 부를 수 없으면(인증 오류, 429, 형식 위반) 규칙만으로 만든 결과로 물러서고
   QueryIntent.degraded로 그 사실을 알린다.

filters는 유형과 무관하게 항상 채운다. 실제 질의는 "고1 토론 자료"처럼 섞여 들어오므로
유형 하나로는 표현되지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum

from llm_client import generate_completion
from prompt import classify_prompt, extract_json


class QueryType(str, Enum):
    TOPIC = "topic"          # 주제/키워드 검색
    TITLE = "title"          # 제목 정확 매칭
    ATTRIBUTE = "attribute"  # 속성 필터 (학년/과목/날짜)


@dataclass
class QueryFilters:
    grade: str | None = None
    subject: str | None = None
    date_from: str | None = None  # ISO 8601 (YYYY-MM-DD)
    date_to: str | None = None    # ISO 8601 (YYYY-MM-DD)


@dataclass
class QueryIntent:
    query_type: QueryType
    keyword: str | None = None  # TOPIC/TITLE 검색에 쓸 키워드 또는 제목
    filters: QueryFilters = field(default_factory=QueryFilters)
    # LLM을 쓰지 못해 규칙만으로 대충 만든 결과인지. 화면에서 그 사실을 알려야 한다.
    degraded: bool = False


# 질의가 제목을 이만큼 닮으면 TITLE 후보로 본다. 질의에는 "페이지 보여줘" 같은
# 군더더기가 붙으므로 완전 일치를 요구할 수 없다.
TITLE_MATCH_THRESHOLD = 0.62

# 그리고 제목의 낱말이 이만큼은 질의에 실제로 들어 있어야 한다.
#
# 문자열 유사도만으로는 가를 수 없다. "유전자 편집 관련 교육 자료 찾아줘"가
# `유전자 편집 기술 관련 교육 교안`에 0.70으로 걸리는데, 정작 제목의 핵심인
# `기술`·`교안`이 질의에 없다. 그런데 이 0.70이 진짜 제목 질의인
# "토론수업 계획안 페이지 보여줘"(0.67)보다 높아서, 임계값을 올리면 정탐이 먼저 죽는다.
#
# 낱말 포함률로 보면 갈린다 - 진짜 제목 질의는 5건 모두 1.00, 위 오탐은 0.67.
TITLE_COVERAGE_THRESHOLD = 0.9

# 제목 낱말을 비교하기 전에 떼어낼 문장부호. 데이터셋에 `“개발과 환경 보전...”`처럼
# 곡선 따옴표가 붙은 제목이 있는데 사용자가 그대로 타이핑하지는 않는다.
_TRIM = "“”\"'.,?!·"

# 데이터셋 실측 기준 값. "한국사"를 "사회"보다 먼저 봐야 잘못 매칭되지 않는다.
# "정보"는 Notion 속성 선택지에 없고 본문에만 있는 과목이라 빠뜨리기 쉽다.
_GRADES = ["고1", "고2", "고3", "중1", "중2", "중3"]
_SUBJECTS = ["한국사", "국어", "영어", "수학", "사회", "과학", "정보"]

_DATE_HINT = re.compile(
    r"지난달|이번\s?달|지난\s?학기|이번\s?학기|최근|작년|올해|\d{4}\s?년|\d{1,2}\s?월"
)

# 규칙 분기에서 keyword를 뽑을 때 걷어낼 말들.
_STOPWORDS = [
    "찾아줘", "찾아", "요약해줘", "보여줘", "알려줘", "해줘", "있어", "있나",
    "관련", "페이지", "자료", "교과", "과목", "내용", "정도",
]

_LLM_TYPE_MAP = {
    "keyword": QueryType.TOPIC,
    "title": QueryType.TITLE,
    "filter": QueryType.ATTRIBUTE,
}


def _title_coverage(title: str, raw_query: str) -> float:
    """제목의 낱말 중 질의에 실제로 등장하는 비율."""
    words = [w.strip(_TRIM) for w in re.split(r"\s+", title)]
    words = [w for w in words if len(w) >= 2]
    if not words:
        return 1.0
    return sum(1 for w in words if w in raw_query) / len(words)


def _match_title(raw_query: str, known_titles: list[str]) -> str | None:
    """질의가 데이터셋 제목 중 하나를 가리키는지 본다.

    닮은 정도(SequenceMatcher)와 제목 낱말 포함률을 둘 다 넘겨야 인정한다.
    """
    best, best_ratio = None, 0.0
    for title in known_titles:
        ratio = SequenceMatcher(None, title, raw_query).ratio()
        if ratio < TITLE_MATCH_THRESHOLD or ratio <= best_ratio:
            continue
        if _title_coverage(title, raw_query) < TITLE_COVERAGE_THRESHOLD:
            continue
        best, best_ratio = title, ratio
    return best


def _leftover_keyword(raw_query: str, *taken: str | None) -> str | None:
    """속성 단어와 상투어를 걷어낸 나머지를 keyword로 돌려준다."""
    text = raw_query
    for word in [*(t for t in taken if t), *_STOPWORDS]:
        text = text.replace(word, " ")
    cleaned = re.sub(r"\s+", " ", text).strip(" ?!.,")
    return cleaned or None


def _fallback(raw_query: str) -> QueryIntent:
    """LLM을 쓸 수 없을 때의 차선책.

    상투어만 걷어낸 나머지를 그대로 키워드로 본다. 날짜 표현("지난달")은 해석하지
    못하므로 결과가 비거나 엉뚱해질 수 있지만, 화면 전체가 죽는 것보다는 낫다.
    """
    return QueryIntent(
        query_type=QueryType.TOPIC,
        keyword=_leftover_keyword(raw_query),
        degraded=True,
    )


def _from_llm(raw_query: str) -> QueryIntent:
    """LLM에 분류를 맡긴다.

    경량 모델은 스펙에 없는 type을 주거나(예: "grade") 필드를 통째로 빠뜨리기도 한다.
    값이 이상하면 있는 필드로 유형을 되짚는다.

    API 오류(인증 만료, 429)나 JSON 파싱 실패로 아예 답을 못 받는 경우도 있어
    그때는 규칙만으로 만든 결과로 물러선다.
    """
    try:
        parsed = extract_json(generate_completion(classify_prompt(raw_query)))
    except Exception:
        return _fallback(raw_query)

    grade = parsed.get("grade") or None
    subject = parsed.get("subject") or None
    filters = QueryFilters(
        grade=grade,
        subject=subject,
        date_from=parsed.get("date_from") or None,
        date_to=parsed.get("date_to") or None,
    )

    # 프롬프트에 "상투어와 학년·과목·날짜 표현은 걷어내라"고 적어뒀지만 잘 안 지킨다.
    # "2025년 10월에 작성된 자료 찾아줘"에 keyword="자료", "체육 자료 찾아줘"에
    # keyword="체육"(subject와 중복)을 그대로 담아 보낸다. 남은 "자료"가 검색어로
    # 살아나면 날짜 조건만 봐야 할 질의가 키워드 질의로 바뀌어 결과가 깎인다.
    # 규칙 경로와 같은 방식으로 한 번 더 걷어내는 편이 확실하다.
    keyword = _leftover_keyword(parsed.get("keyword") or "", grade, subject)

    # 모델이 준 type이 필드와 어긋나면 필드를 믿는다. keyword를 비워놓고 type만
    # "keyword"라고 답하는 일이 잦은데("지난달 작성된 자료 찾아줘"), 그대로 두면
    # 검색어 없는 TOPIC 질의가 돼서 필터를 통과한 전부가 동점으로 쏟아진다.
    query_type = _LLM_TYPE_MAP.get(parsed.get("type", ""))
    if not keyword:
        query_type = QueryType.ATTRIBUTE
    elif query_type is None:
        query_type = QueryType.TOPIC

    return QueryIntent(query_type=query_type, keyword=keyword, filters=filters)


def classify_query(
    raw_query: str, known_titles: list[str] | None = None
) -> QueryIntent:
    """자연어 질의를 분석해 QueryIntent로 변환한다.

    known_titles를 넘기면 제목 매칭을 먼저 시도한다 (LLM 호출 없이 끝나는 경로).
    """
    raw_query = raw_query.strip()

    if known_titles:
        matched = _match_title(raw_query, known_titles)
        if matched:
            return QueryIntent(query_type=QueryType.TITLE, keyword=matched)

    grade = next((g for g in _GRADES if g in raw_query), None)
    subject = next((s for s in _SUBJECTS if s in raw_query), None)

    if (grade or subject) and not _DATE_HINT.search(raw_query):
        keyword = _leftover_keyword(raw_query, grade, subject)
        return QueryIntent(
            query_type=QueryType.TOPIC if keyword else QueryType.ATTRIBUTE,
            keyword=keyword,
            filters=QueryFilters(grade=grade, subject=subject),
        )

    return _from_llm(raw_query)
