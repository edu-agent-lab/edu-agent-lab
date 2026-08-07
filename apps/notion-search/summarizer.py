"""검색 결과 요약. (담당: 나)

mcp_client가 반환한 NotionPage들을 받아 각각 LLM 요약을 생성한다.
"""

from __future__ import annotations

from mcp_client import NotionPage
from llm_client import generate_completion
from prompt import SUMMARIZE_PAGE_PROMPT


def summarize_page(page: NotionPage) -> str:
    """페이지 본문을 3~4문장으로 요약한다."""
    prompt = SUMMARIZE_PAGE_PROMPT.format(title=page.title, content=page.content)
    return generate_completion(prompt)


def summarize_results(pages: list[NotionPage]) -> dict[str, str]:
    """검색 결과 각각을 요약해 {page_id: summary} 형태로 반환한다."""
    return {page.page_id: summarize_page(page) for page in pages}
