"""Notion MCP 서버 클라이언트.

데이터셋이 14건뿐이라 질의마다 검색하지 않고 전체를 한 번 읽어 캐싱한다.
필터링·매칭은 search 쪽 책임이고, 여기서는 Notion 응답을 NotionPage로 옮기기만 한다.

연동 방식(로컬 서버 + NOTION_TOKEN)은 README "MCP 연동 방식" 참고.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
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


# --- 재시도 정책 (Day3 Step6 확정) -----------------------------------------
# Notion API는 초당 약 3회. fetch_all_pages()가 목록 1회 + 본문 N회를 순차로 부르는데,
# 14건 기준 왕복만으로도 초당 3회에 근접해서 여유가 크지 않다.
#
# 가이드 예시처럼 매 호출에 고정 sleep을 넣는 대신, 직전 호출로부터 흐른 시간을 재서
# 모자란 만큼만 쉰다. 왕복이 이미 느리면 추가 대기가 0이 되므로 손해 볼 일이 없다.
MIN_CALL_INTERVAL = 1 / 3

MAX_RETRIES = 3
BACKOFF_SECONDS = (0.5, 1.0, 2.0)

# 서버가 Retry-After로 비정상적으로 긴 값을 주면 그대로 기다리지 않는다.
# 첫 화면이 그만큼 멈추느니 실패로 끝내고 사용자에게 알리는 편이 낫다.
MAX_RETRY_WAIT = 10.0

# 다시 걸면 될 만한 오류만 재시도한다. 401(토큰 문제)이나 404는 몇 번을 걸어도 같다.
_RETRYABLE = re.compile(
    r"429|rate[\s_-]?limit|50[234]|timeout|timed out|ECONNRESET|socket hang up",
    re.IGNORECASE,
)
_RETRY_AFTER = re.compile(r"retry[\s_-]?after\D{0,4}(\d+(?:\.\d+)?)", re.IGNORECASE)


class MCPCallError(RuntimeError):
    """MCP tool 호출이 재시도 후에도 실패했다."""


_last_call_at = 0.0


async def _throttle() -> None:
    """직전 호출과의 간격이 좁으면 모자란 만큼만 쉬어간다."""
    global _last_call_at
    gap = time.monotonic() - _last_call_at
    if gap < MIN_CALL_INTERVAL:
        await asyncio.sleep(MIN_CALL_INTERVAL - gap)
    _last_call_at = time.monotonic()


def _error_text(result: Any) -> str | None:
    """tool 응답이 에러면 그 내용을, 정상이면 None을 돌려준다.

    MCP는 tool 실패를 예외가 아니라 isError 플래그로 알려준다. 그대로 _payload()에
    넘기면 에러 메시지를 JSON으로 파싱하려다 엉뚱한 곳에서 터진다.
    """
    if not getattr(result, "isError", False):
        return None
    parts = [getattr(c, "text", "") for c in (result.content or [])]
    return " ".join(p for p in parts if p) or "알 수 없는 오류"


def _wait_seconds(error: str, attempt: int) -> float:
    """서버가 알려준 Retry-After를 우선하고, 없으면 정해둔 백오프를 쓴다."""
    matched = _RETRY_AFTER.search(error)
    if matched:
        return min(float(matched.group(1)), MAX_RETRY_WAIT)
    return BACKOFF_SECONDS[attempt]


async def _call(session: ClientSession, tool: str, arguments: dict) -> dict:
    """tool을 호출해 JSON 페이로드를 돌려준다. 일시적인 실패는 재시도한다."""
    error = ""
    for attempt in range(MAX_RETRIES + 1):
        await _throttle()
        try:
            result = await session.call_tool(tool, arguments=arguments)
            failed = _error_text(result)
            if failed is None:
                return _payload(result)
            error = failed
        except Exception as exc:  # 전송 계층 오류도 같은 정책으로 다룬다
            error = f"{type(exc).__name__}: {exc}"

        if attempt == MAX_RETRIES or not _RETRYABLE.search(error):
            break
        await asyncio.sleep(_wait_seconds(error, attempt))

    raise MCPCallError(f"{tool} 호출 실패 ({attempt + 1}회 시도): {error[:300]}")


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
                data = await _call(session, TOOL_QUERY, args)
                rows.extend(data["results"])
                if not data.get("has_more"):
                    break
                cursor = data["next_cursor"]

            # 본문은 페이지마다 따로 조회해야 한다. 호출 간격과 429는 _call()이
            # 함께 처리하므로 여기서는 순서대로 부르기만 한다.
            pages = []
            for row in rows:
                md = await _call(session, TOOL_MARKDOWN, {"page_id": row["id"]})
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
    """데이터셋 전체를 읽어 캐싱한다. 두 번째 호출부터는 네트워크를 타지 않는다.

    재시도로도 복구되지 않으면 MCPCallError를 올린다. 호출부에서 사용자에게 보여줄
    메시지로 바꿔야 한다.
    """
    global _cache
    if _cache is None or refresh:
        _cache = asyncio.run(_fetch_all())
    return _cache
