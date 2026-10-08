"""로컬 임베딩 모델(dragonkue/BGE-m3-ko) 클라이언트.

OpenAI API 대신 허깅페이스 모델을 로컬에서 돌린다. API 키/비용이 필요 없는 대신,
최초 실행 시 모델 가중치(0.6B 파라미터)를 다운로드하고, 추론도 로컬 CPU/GPU로
돌아가서 OpenAI API 호출보다 느리다.
"""
import os
from functools import lru_cache

import torch
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

load_dotenv()

DEFAULT_EMBEDDING_MODEL = "dragonkue/BGE-m3-ko"

BATCH_SIZE = 32


def _device():
    # SentenceTransformer는 device를 안 주면 CPU로 돈다. Apple Silicon이면 MPS(GPU)를
    # 써야 수십 배 빠르다 — 안 썼더니 5789건 인코딩에 45시간이 뜬 걸 보고 알았다.
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


@lru_cache(maxsize=1)
def _model():
    name = os.environ.get("EMBEDDING_MODEL", "").strip() or DEFAULT_EMBEDDING_MODEL
    return SentenceTransformer(name, device=_device())


def embed_texts(texts, batch_size=BATCH_SIZE):
    """텍스트 리스트를 같은 순서의 임베딩 벡터 리스트로 변환한다.
    normalize_embeddings=True로 미리 단위벡터화해서, 코사인 유사도가 곧 내적이 되게 한다."""
    model = _model()
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=len(texts) > 1,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return vectors.tolist()


def embed_query(text):
    return embed_texts([text])[0]
