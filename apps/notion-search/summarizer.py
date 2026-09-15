"""검색 결과 페이지 1건을 2~3문장으로 요약한다."""

from __future__ import annotations

import re

from llm_client import generate_completion
from prompt import SUMMARIZE_PAGE_PROMPT

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
    cleaned = clean_content(content)
    if not cleaned:
        # 본문이 없으면 LLM이 제목만 보고 내용을 지어내는 걸 실제로 확인했다
        # (Day6 노이즈 테스트). 호출 자체를 막는 게 프롬프트로 막는 것보다 확실하다.
        return "본문이 비어 있어 요약할 수 없습니다."
    prompt = SUMMARIZE_PAGE_PROMPT.format(title=title, content=cleaned)
    return generate_completion(prompt)
