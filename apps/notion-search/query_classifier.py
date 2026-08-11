"""자연어 질의 -> QueryIntent 변환. (담당: 나)

mcp_client.search_pages()가 이 모듈이 만든 QueryIntent를 입력으로 받는다.

판단 로직 (Day2 Step 2 결정: 하이브리드):
1차 규칙 기반 - 학년/과목이 텍스트에 그대로 등장하고 날짜 표현이 없으면, LLM 호출 없이 바로 ATTRIBUTE로 판정.
2차 LLM 분류 - 날짜 표현(상대적 날짜라 규칙만으로는 해석 불가)이 섞여 있거나 속성 신호가 전혀 없는 나머지는
prompt.CLASSIFY_QUERY_PROMPT + llm_client.generate_completion()으로 유형+파라미터를 한 번에 추출한다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum

from llm_client import generate_completion
from prompt import CLASSIFY_QUERY_PROMPT


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


# docs/notion-search/golden-set.md 실제 데이터 기준 값. 데이터셋에 새 학년/과목이 추가되면 같이 갱신 필요.
_GRADES = ["고1", "고2", "고3", "중1", "중2", "중3", "초1", "초2", "초3", "초4", "초5", "초6"]
_SUBJECTS = ["국어", "영어", "수학", "사회", "과학", "한국사"]
_DATE_HINT_PATTERN = re.compile(r"지난달|이번달|지난\s?학기|이번\s?학기|최근|작년|올해|\d{4}년|\d{1,2}월")

_LLM_TYPE_MAP = {"keyword": QueryType.TOPIC, "title": QueryType.TITLE, "filter": QueryType.ATTRIBUTE}


def classify_query(raw_query: str) -> QueryIntent:
    """자연어 질의를 분석해 QueryIntent로 변환한다."""
    grade = next((g for g in _GRADES if g in raw_query), None)
    subject = next((s for s in _SUBJECTS if s in raw_query), None)
    has_date_hint = bool(_DATE_HINT_PATTERN.search(raw_query))

    if (grade or subject) and not has_date_hint:
        return QueryIntent(query_type=QueryType.ATTRIBUTE, filters=QueryFilters(grade=grade, subject=subject))

    response = generate_completion(CLASSIFY_QUERY_PROMPT.format(user_query=raw_query))
    parsed = json.loads(response)
    query_type = _LLM_TYPE_MAP[parsed["type"]]

    return QueryIntent(
        query_type=query_type,
        keyword=parsed.get("keyword"),
        filters=QueryFilters(
            grade=parsed.get("grade"),
            subject=parsed.get("subject"),
            # TODO(팀원): date_range는 LLM이 "지난달"처럼 자연어 그대로 줄 수 있음.
            # QueryFilters.date_from/date_to(ISO 8601)로 변환하는 파싱 규칙을 아직 안 정함.
        ),
    )
