"""검색 결과 요약.

search()가 돌려준 PageMeta를 받아 페이지별 요약을 만든다.
"""

from __future__ import annotations

import re

from llm_client import generate_completion
from prompt import SUMMARIZE_PAGE_PROMPT
from search import PageMeta

# 요약에 넣을 본문 길이 상한. 가장 긴 페이지가 2092자라 넉넉하지만,
# 데이터가 늘어도 토큰이 폭주하지 않도록 잘라둔다.
MAX_CONTENT_CHARS = 3000

# notion-mcp-server가 빈 블록을 이 태그로 내보낸다. 요약에 넣을 이유가 없다.
_NOISE = re.compile(r"<empty-block/>|^—$", re.MULTILINE)


def clean_content(markdown: str) -> str:
    text = _NOISE.sub("", markdown)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:MAX_CONTENT_CHARS]


def summarize_text(title: str, content: str) -> str:
    """제목과 본문만으로 요약한다.

    PageMeta는 해시가 안 돼서 Streamlit 캐시 키로 못 쓴다. 캐싱하는 쪽이
    문자열만 넘길 수 있도록 이 형태를 따로 둔다.
    """
    prompt = SUMMARIZE_PAGE_PROMPT.format(title=title, content=clean_content(content))
    return generate_completion(prompt)


def summarize_page(meta: PageMeta) -> str:
    """페이지 본문을 2~3문장으로 요약한다."""
    return summarize_text(meta.title, meta.page.content)


def summarize_results(metas: list[PageMeta]) -> dict[str, str]:
    """검색 결과를 요약해 {page_id: summary}로 반환한다.

    페이지마다 LLM을 한 번씩 부르므로 결과가 많으면 그만큼 느려진다.
    호출부에서 표시할 만큼만 잘라 넘기는 편이 낫다.
    """
    return {m.page.page_id: summarize_page(m) for m in metas}
