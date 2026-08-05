"""Notion MCP 서버 클라이언트. (담당: 팀원)

query_classifier.QueryIntent를 받아 검색을 수행하고, NotionPage 목록을 반환한다.
연동 방식(인증, 접속 방식 등) 조사 내용은 README.md의 "MCP 연동 방식" 참고.
"""

from __future__ import annotations

from dataclasses import dataclass

from query_classifier import QueryIntent


@dataclass
class NotionPage:
    page_id: str
    title: str
    url: str
    content: str
    properties: dict


def search_pages(intent: QueryIntent) -> list[NotionPage]:
    """QueryIntent에 맞는 Notion 페이지를 MCP tool call로 검색해 본문까지 채운
    NotionPage 리스트로 반환한다.

    TODO(팀원):
    - MCP 서버 연결/인증
    - intent.query_type에 따라 검색 tool call 구성 (키워드 검색 vs 속성 필터)
    - 응답 파싱 -> NotionPage 리스트로 변환 (본문 포함, summarizer가 바로 쓸 수 있게)
    - 결과 없음 -> 빈 리스트 반환
    """
    raise NotImplementedError
