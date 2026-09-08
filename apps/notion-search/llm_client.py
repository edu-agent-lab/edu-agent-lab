"""LLM API 클라이언트.

OpenAI API를 쓴다. 다른 제공자로 갈아탈 때도 이 파일만 고치면 된다.
CLOVA Studio에서 옮겨올 때도 base_url과 키 이름만 바꾼 게 전부였다.

    https://platform.openai.com/docs/api-reference/chat
"""

from __future__ import annotations

import os
import time
from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI

from retry import MAX_ATTEMPTS, backoff_delay

load_dotenv()

# 분류·요약 둘 다 가벼운 작업이라 mini로 충분하다. 골든셋 한 번 도는 데
# 입력 5만 / 출력 3천 토큰 수준이라 실행당 30원이 안 된다.
DEFAULT_MODEL = "gpt-5-mini"


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    # .env에 값을 붙여넣을 때 공백이 섞이는 일이 잦아 양쪽을 털어낸다.
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY가 없습니다. .env.example을 복사해 .env를 만들고 키를 채우세요."
        )
    return OpenAI(api_key=api_key)


def _model() -> str:
    return os.environ.get("OPENAI_MODEL", "").strip() or DEFAULT_MODEL


def _sampling_kwargs(model: str) -> dict[str, object]:
    """모델이 받아주는 샘플링 인자만 골라 넘긴다.

    원래 이 자리에는 temperature=0이 있었다. 분류 결과가 매 호출마다 달라지면
    골든셋 점수를 신뢰할 수 없어서였다. 그런데 GPT-5 계열은 temperature가
    1로 고정이고 다른 값을 넘기면 400이 난다. 재현성은 프롬프트와 후처리
    (query_classifier의 필드 우선 판정, _leftover_keyword)로 받치고 있으니
    지원하는 모델에서만 0을 넘긴다.
    """
    if model.startswith(("gpt-5", "o1", "o3", "o4")):
        return {}
    return {"temperature": 0}


def generate_completion(prompt: str, system: str | None = None) -> str:
    """프롬프트를 LLM에 보내고 텍스트 응답을 반환한다.

    실패하면 최대 MAX_ATTEMPTS번 지수 백오프로 재시도한다. 오류 종류를 나누지
    않고 다 재시도한다 — 호출량이 질의당 최대 9콜 정도라 굳이 나눌 실익이 적고,
    재시도해도 실패할 오류는 몇 초 안에 그대로 드러난다.

    다만 OpenAI로 옮긴 뒤로 이 판단이 조금 약해졌다. 잔액 소진(429
    insufficient_quota)과 키 오류(401)는 재시도해도 절대 안 풀리는데 호출마다
    2.5초를 그냥 버린다. 골든셋 한 바퀴면 25초쯤 된다. 나눌지는 팀 논의 후에.
    """
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    model = _model()
    last_exc: Exception = RuntimeError("generate_completion: 알 수 없는 오류")

    for attempt in range(MAX_ATTEMPTS):
        try:
            response = _client().chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                **_sampling_kwargs(model),  # type: ignore[arg-type]
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001 - 종류를 안 가리고 재시도
            last_exc = exc
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(backoff_delay(attempt))

    raise last_exc
