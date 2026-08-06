"""Day1 가이드 Step 5: notion-search 도구 수동 호출 테스트.

mcp_client.py 구현 전, MCP 서버 연결과 tool 호출이 실제로 되는지 확인하기 위한
일회성 스크립트. NOTION_TOKEN은 .env에서 읽는다 (.env.example 참고).

원격 서버(https://mcp.notion.com/mcp)는 OAuth만 지원해서 Integration Secret으로는
401이 난다 (README "옵션 A" 참고). 대신 로컬 서버(README "옵션 B",
@notionhq/notion-mcp-server)를 npx로 띄워 stdio로 붙는다 - NOTION_TOKEN 하나로 인증됨.

실행: cd apps/notion-search && python manual_mcp_test.py "검색어"
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
QUERY = sys.argv[1] if len(sys.argv) > 1 else "토론 수업"

SERVER_PARAMS = StdioServerParameters(
    command="npx",
    args=["-y", "@notionhq/notion-mcp-server"],
    env={**os.environ, "NOTION_TOKEN": NOTION_TOKEN},
)


async def main() -> None:
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("=== tools/list ===")
            for t in tools.tools:
                print(t.name)

            print(f"\n=== API-post-search(query={QUERY!r}) ===")
            result = await session.call_tool("API-post-search", arguments={"query": QUERY})
            print(result)


if __name__ == "__main__":
    asyncio.run(main())
