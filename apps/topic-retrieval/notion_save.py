"""생성한 수업자료를 Notion 페이지로 저장한다.

프로젝트 1(apps/notion-search)과 같은 로컬 MCP 서버(@notionhq/notion-mcp-server)와 같은
NOTION_TOKEN을 쓴다. 코드는 가져오지 않고 필요한 만큼만 따로 둔다 — notion-search의
mcp_client는 읽기 전용 데이터셋 캐싱용이라 구조가 다르다.

저장은 두 번의 호출이다:

1. API-post-page: 부모 페이지 아래 제목만 있는 빈 페이지를 만든다
2. API-update-page-markdown(replace_content): 생성 결과 마크다운을 그대로 본문으로 넣는다

블록 JSON으로 바꾸지 않고 마크다운 엔드포인트를 쓰는 이유: 결과물에 표(루브릭)·번호 목록·
중첩 목록이 섞여 있어서 블록 변환기를 직접 만들면 그게 제일 큰 코드가 된다.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# 팀스페이스 "실전 프로젝트 2: AI 챗봇 기반 수업계획안 생성" 페이지. 다른 곳에 저장하려면
# .env의 NOTION_PARENT_PAGE_ID로 바꾼다 (integration이 그 페이지에 연결돼 있어야 한다).
DEFAULT_PARENT_PAGE_ID = "0e09feee-0a11-8221-9e31-01f02b8db56c"


class NotionSaveError(RuntimeError):
    """페이지 생성이나 본문 저장이 실패했다."""


def is_configured() -> bool:
    return bool(os.environ.get("NOTION_TOKEN", "").strip())


def _parent_id() -> str:
    return os.environ.get("NOTION_PARENT_PAGE_ID", "").strip() or DEFAULT_PARENT_PAGE_ID


def _server_params():
    from mcp import StdioServerParameters

    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        raise NotionSaveError("NOTION_TOKEN이 없습니다. 저장소 루트 .env에 채우세요.")
    return StdioServerParameters(
        command="npx",
        args=["-y", "@notionhq/notion-mcp-server"],
        env={**os.environ, "NOTION_TOKEN": token},
    )


async def _call(session, tool: str, arguments: dict) -> dict:
    """MCP는 실패를 예외가 아니라 is_error로 알린다. 그대로 JSON 파싱하면 엉뚱하게 터진다."""
    result = await session.call_tool(tool, arguments=arguments)
    text = " ".join(getattr(c, "text", "") for c in (result.content or []))
    if getattr(result, "is_error", False):
        raise NotionSaveError(f"{tool} 실패: {text[:300]}")
    return json.loads(text)


async def _save(title: str, markdown: str) -> str:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            page = await _call(
                session,
                "API-post-page",
                {
                    "parent": {"page_id": _parent_id()},
                    "properties": {"title": {"title": [{"text": {"content": title}}]}},
                },
            )
            await _call(
                session,
                "API-update-page-markdown",
                {
                    "page_id": page["id"],
                    "type": "replace_content",
                    "replace_content": {"new_str": markdown},
                },
            )
            return page["url"]


def save_material(title: str, markdown: str) -> str:
    """Notion에 페이지를 만들고 URL을 돌려준다."""
    return asyncio.run(_save(title, markdown))


def page_title(*, school_level: str, subject: str, topic: str, material_type: str) -> str:
    return f"[{material_type}] {topic} ({school_level} {subject})"
