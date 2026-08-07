"""자연어 질의 -> QueryIntent 변환. (담당: 나)

mcp_client.search_pages()가 이 모듈이 만든 QueryIntent를 입력으로 받는다.
필터 추출(학년/과목/날짜)이 필요한 ATTRIBUTE 타입은 LLM(llm_client) + prompt.py 템플릿을 활용해 구현 예정.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


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


def classify_query(raw_query: str) -> QueryIntent:
    """자연어 질의를 분석해 QueryIntent로 변환한다.

    TODO:
    - TOPIC/TITLE/ATTRIBUTE 판별 로직 (규칙 기반 우선, 애매하면 LLM 보조)
    - ATTRIBUTE 타입일 때 prompt.EXTRACT_FILTERS_PROMPT + llm_client.generate_completion()으로
      학년/과목/날짜 추출 -> QueryFilters로 파싱
    """
    raise NotImplementedError
