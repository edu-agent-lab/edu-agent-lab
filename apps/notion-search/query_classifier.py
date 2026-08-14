"""자연어 질의 -> QueryIntent 변환.

판단 순서 (Day2 Step2 하이브리드를 데이터에 맞춰 조정):

1. 제목 매칭 - 데이터셋 제목 14개와 대조한다. 걸리면 LLM을 부르지 않는다.
   목록을 손에 쥐고 있으므로 이게 가장 정확하고 공짜다.
2. 규칙 기반 - 학년/과목이 그대로 등장하고 날짜 표현이 없으면 바로 판정한다.
   이때 속성 단어를 걷어낸 나머지를 keyword로 남긴다. "부등식 관련 수학 자료"에서
   "부등식"을 잃으면 수학 자료가 전부 나와버린다.
3. LLM - 날짜 표현이 섞였거나 속성 신호가 없는 나머지.

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


# 질의가 제목을 이만큼 닮으면 TITLE로 본다. 질의에는 "페이지 보여줘" 같은 군더더기가
# 붙으므로 완전 일치를 요구할 수 없다.
TITLE_MATCH_THRESHOLD = 0.62

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


def _match_title(raw_query: str, known_titles: list[str]) -> str | None:
    """질의가 데이터셋 제목 중 하나를 가리키는지 본다."""
    best, best_ratio = None, 0.0
    for title in known_titles:
        ratio = SequenceMatcher(None, title, raw_query).ratio()
        if ratio > best_ratio:
            best, best_ratio = title, ratio
    return best if best_ratio >= TITLE_MATCH_THRESHOLD else None


def _leftover_keyword(raw_query: str, *taken: str | None) -> str | None:
    """속성 단어와 상투어를 걷어낸 나머지를 keyword로 돌려준다."""
    text = raw_query
    for word in [*(t for t in taken if t), *_STOPWORDS]:
        text = text.replace(word, " ")
    cleaned = re.sub(r"\s+", " ", text).strip(" ?!.,")
    return cleaned or None


def _from_llm(raw_query: str) -> QueryIntent:
    """LLM에 분류를 맡긴다.

    경량 모델은 스펙에 없는 type을 주거나(예: "grade") 필드를 통째로 빠뜨리기도 한다.
    값이 이상하면 있는 필드로 유형을 되짚는다.
    """
    parsed = extract_json(generate_completion(classify_prompt(raw_query)))

    keyword = parsed.get("keyword") or None
    filters = QueryFilters(
        grade=parsed.get("grade") or None,
        subject=parsed.get("subject") or None,
        date_from=parsed.get("date_from") or None,
        date_to=parsed.get("date_to") or None,
    )

    query_type = _LLM_TYPE_MAP.get(parsed.get("type", ""))
    if query_type is None:
        query_type = QueryType.TOPIC if keyword else QueryType.ATTRIBUTE

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
