"""수업자료 생성용 LLM 클라이언트.

`apps/notion-search/llm_client.py`와 같은 구조다 — 거기서 검증된 패턴(키 공백 제거,
GPT-5 계열 temperature 분기, 지수 백오프 재시도)을 그대로 쓴다. 공통 모듈로 빼지 않고
복사한 이유는 호출부가 두 앱뿐이라서다. 종합 프로젝트에서 세 번째 호출부가 생기면
`packages/`로 옮긴다.

임베딩은 로컬 모델이라 키가 필요 없고, **생성에만 OPENAI_API_KEY가 필요하다.**
키가 없으면 검색까지는 그대로 동작한다. 키는 저장소 루트 `.env`에서 읽는다.
"""

from __future__ import annotations

import os
import random
import time
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# .env는 저장소 루트에 하나만 둔다 (앱마다 두면 키를 여러 벌 관리해야 한다).
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# 계획안 본문이 산출물이라 요약보다 출력이 길지만(2~4천 토큰) mini로 충분하다.
DEFAULT_MODEL = "gpt-5-mini"

MAX_ATTEMPTS = 3
_BASE_DELAY = 0.5
_BACKOFF_FACTOR = 4


class LLMNotConfigured(RuntimeError):
    """OPENAI_API_KEY가 없다. 검색은 되지만 생성은 못 한다."""


def is_configured() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


@lru_cache(maxsize=1)
def _client():
    from openai import OpenAI

    # .env에 값을 붙여넣을 때 공백이 섞이는 일이 잦아 양쪽을 털어낸다.
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise LLMNotConfigured(
            "OPENAI_API_KEY가 없습니다. .env.example을 복사해 .env를 만들고 키를 채우세요."
        )
    return OpenAI(api_key=api_key)


def _model() -> str:
    return os.environ.get("OPENAI_MODEL", "").strip() or DEFAULT_MODEL


def _sampling_kwargs(model: str) -> dict:
    """GPT-5 계열은 temperature가 1 고정이라 다른 값을 넘기면 400이 난다."""
    if model.startswith(("gpt-5", "o1", "o3", "o4")):
        return {}
    return {"temperature": 0.3}


def _backoff(attempt: int) -> float:
    return _BASE_DELAY * (_BACKOFF_FACTOR**attempt) + random.uniform(0, 0.3)


def generate(prompt: str, system: str | None = None) -> str:
    """프롬프트를 보내고 텍스트를 받는다. 실패하면 지수 백오프로 재시도한다."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    model = _model()
    last: Exception = RuntimeError("generate: 알 수 없는 오류")
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = _client().chat.completions.create(
                model=model, messages=messages, **_sampling_kwargs(model)
            )
            return (response.choices[0].message.content or "").strip()
        except LLMNotConfigured:
            raise
        except Exception as exc:  # noqa: BLE001 - 종류를 안 가리고 재시도
            last = exc
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(_backoff(attempt))
    raise last
