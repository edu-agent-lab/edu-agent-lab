"""재시도 타이밍 계산. (Day3 Step6)

mcp_client.py, llm_client.py 두 곳에서만 쓴다. "무엇을 재시도할지"는 프로바이더마다
달라서(MCP는 is_error 필드, OpenAI는 예외 타입) 호출부에 각각 두고, 여기서는 지수
백오프 대기 시간만 계산한다.
"""

from __future__ import annotations

import random

MAX_ATTEMPTS = 3
_BASE_DELAY = 0.5  # seconds
_BACKOFF_FACTOR = 4


def backoff_delay(attempt: int) -> float:
    """attempt(0부터)번째 실패 후 대기 시간. 0.5s -> 2s -> 8s + 약간의 지터."""
    return _BASE_DELAY * (_BACKOFF_FACTOR**attempt) + random.uniform(0, 0.3)
