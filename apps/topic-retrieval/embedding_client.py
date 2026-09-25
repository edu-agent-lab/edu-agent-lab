"""OpenAI 임베딩 클라이언트. notion-search/llm_client.py와 같은 패턴(.env, lru_cache)."""
import os
from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

# OpenAI 임베딩 API는 한 요청에 여러 입력을 배치로 보낼 수 있다.
BATCH_SIZE = 100


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY가 없습니다. .env.example을 복사해 .env를 만들고 키를 채우세요."
        )
    return OpenAI(api_key=api_key)


def _model() -> str:
    return os.environ.get("OPENAI_EMBEDDING_MODEL", "").strip() or DEFAULT_EMBEDDING_MODEL


def embed_texts(texts, batch_size=BATCH_SIZE):
    """텍스트 리스트를 같은 순서의 임베딩 벡터 리스트로 변환한다."""
    client = _client()
    model = _model()
    vectors = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        resp = client.embeddings.create(model=model, input=batch)
        vectors.extend(item.embedding for item in resp.data)
    return vectors


def embed_query(text):
    return embed_texts([text])[0]
