import asyncio
import os
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()
NOTION_TOKEN = os.environ["NOTION_TOKEN"]

SERVER_PARAMS = StdioServerParameters(
    command="npx",
    args=["-y", "@notionhq/notion-mcp-server"],
    env={**os.environ, "NOTION_TOKEN": NOTION_TOKEN},
)

async def main():
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            for t in tools.tools:
                print(t.name, t.inputSchema)

asyncio.run(main())