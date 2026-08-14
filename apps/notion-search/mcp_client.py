"""Notion MCP 서버 클라이언트.

데이터셋이 14건뿐이라 질의마다 검색하지 않고 전체를 한 번 읽어 캐싱한다.
필터링·매칭은 search 쪽 책임이고, 여기서는 Notion 응답을 NotionPage로 옮기기만 한다.

연동 방식(로컬 서버 + NOTION_TOKEN)은 README "MCP 연동 방식" 참고.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

# 실습용 데이터셋 DB. Notion에서 데이터셋을 다시 복제하면 이 값도 바뀐다.
DATA_SOURCE_ID = "0a49feee-0a11-8375-b694-87846e19329b"

TOOL_QUERY = "API-query-data-source"
TOOL_MARKDOWN = "API-retrieve-page-markdown"

# 데이터셋의 속성 이름. 과목 속성은 이름이 그대로 "다중 선택"이다.
PROP_TITLE = "이름"
PROP_GRADE = "학년"
PROP_SUBJECT = "다중 선택"
PROP_DATE = "날짜"
PROP_SEMESTER = "학기"


@dataclass
class NotionPage:
    page_id: str
    title: str
    url: str
    content: str  # 본문 마크다운 원문
    properties: dict[str, Any]  # Notion 원본 그대로 (가공은 search 쪽에서)


# --- 속성 접근 헬퍼 -------------------------------------------------------
# Notion은 속성 타입마다 응답 모양이 다르고, 값이 없으면 None이나 빈 배열이 온다.
# 실제로 과목 7건, 학년 6건, 날짜 3건이 비어 있어 전부 방어가 필요하다.


def title_of(props: dict) -> str:
    blocks = props.get(PROP_TITLE, {}).get("title", [])
    return blocks[0]["plain_text"] if blocks else ""


def grade_of(props: dict) -> str | None:
    select = props.get(PROP_GRADE, {}).get("select")
    return select["name"] if select else None


def subjects_of(props: dict) -> list[str]:
    return [x["name"] for x in props.get(PROP_SUBJECT, {}).get("multi_select", [])]


def date_of(props: dict) -> str | None:
    """작성일(ISO YYYY-MM-DD). created_time은 데이터셋 복제 시각이라 쓰면 안 된다."""
    date = props.get(PROP_DATE, {}).get("date")
    return date["start"] if date else None


def semester_of(props: dict) -> str | None:
    blocks = props.get(PROP_SEMESTER, {}).get("rich_text", [])
    return blocks[0]["plain_text"] if blocks else None


# --- MCP 호출 -------------------------------------------------------------


def _server_params() -> StdioServerParameters:
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        raise RuntimeError(
            "NOTION_TOKEN이 없습니다. .env.example을 복사해 .env를 만들고 토큰을 채우세요."
        )
    return StdioServerParameters(
        command="npx",
        args=["-y", "@notionhq/notion-mcp-server"],
        env={**os.environ, "NOTION_TOKEN": token},
    )


def _payload(result: Any) -> dict:
    """MCP tool 응답은 TextContent 안에 JSON 문자열로 담겨온다."""
    return json.loads(result.content[0].text)


async def _fetch_all() -> list[NotionPage]:
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            rows: list[dict] = []
            cursor: str | None = None
            while True:
                args: dict[str, Any] = {
                    "data_source_id": DATA_SOURCE_ID,
                    "page_size": 100,
                }
                if cursor:
                    args["start_cursor"] = cursor
                data = _payload(await session.call_tool(TOOL_QUERY, arguments=args))
                rows.extend(data["results"])
                if not data.get("has_more"):
                    break
                cursor = data["next_cursor"]

            # 본문은 페이지마다 따로 조회해야 한다. 14건 순차 호출이면
            # rate limit(분당 180)에 여유가 있다.
            pages = []
            for row in rows:
                md = _payload(
                    await session.call_tool(
                        TOOL_MARKDOWN, arguments={"page_id": row["id"]}
                    )
                )
                pages.append(
                    NotionPage(
                        page_id=row["id"],
                        title=title_of(row["properties"]),
                        url=row.get("url", ""),
                        content=md.get("markdown", ""),
                        properties=row["properties"],
                    )
                )
            return pages


_cache: list[NotionPage] | None = None


def fetch_all_pages(refresh: bool = False) -> list[NotionPage]:
    """데이터셋 전체를 읽어 캐싱한다. 두 번째 호출부터는 네트워크를 타지 않는다."""
    global _cache
    if _cache is None or refresh:
        _cache = asyncio.run(_fetch_all())
    return _cache
