"""LLM API 클라이언트.

CLOVA Studio(HyperCLOVA X)를 쓴다. OpenAI 호환 엔드포인트를 제공해서 openai SDK를
base_url만 바꿔 그대로 사용한다. 다른 제공자로 갈아탈 때도 이 파일만 고치면 된다.

    https://api.ncloud-docs.com/docs/en/clovastudio-openaicompatibility
"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

BASE_URL = "https://clovastudio.stream.ntruss.com/v1/openai"
DEFAULT_MODEL = "HCX-DASH-002"


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    # .env에 값을 붙여넣을 때 공백이 섞이는 일이 잦아 양쪽을 털어낸다.
    api_key = os.environ.get("CLOVA_STUDIO_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "CLOVA_STUDIO_API_KEY가 없습니다. .env.example을 복사해 .env를 만들고 키를 채우세요."
        )
    return OpenAI(api_key=api_key, base_url=BASE_URL)


def _model() -> str:
    return os.environ.get("CLOVA_MODEL", "").strip() or DEFAULT_MODEL


def generate_completion(prompt: str, system: str | None = None) -> str:
    """프롬프트를 LLM에 보내고 텍스트 응답을 반환한다."""
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = _client().chat.completions.create(
        model=_model(),
        messages=messages,  # type: ignore[arg-type]
        # 분류 결과가 매 호출마다 달라지면 골든셋 점수를 신뢰할 수 없다.
        temperature=0,
    )
    return (response.choices[0].message.content or "").strip()
