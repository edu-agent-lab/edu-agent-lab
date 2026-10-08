"""JSONL 전체를 bge-m3-ko로 임베딩해 vecs.npy에 저장한다. (Indexing)

    python index.py            # v2로 전체 임베딩 -> vecs.npy
    python index.py --variant v3 --out vecs_v3.npy
    python index.py --limit 50 # 연결·형태 확인용 (모델 다운로드 포함 첫 실행 점검)

행 순서 = dataset.load_rows() 순서 = JSONL 파일 순서. retrieve.py가 이 순서로
번호를 되짚으므로 JSONL이 바뀌면 다시 돌려야 한다.
"""

from __future__ import annotations

import argparse
import os

import numpy as np

from dataset import MODEL_NAME, VECS, load_rows, to_text


# CPU로 돌릴 때 전 코어를 쓰면 인코딩 동안 머신이 사실상 멈춘다(실측). 2개를 남긴다.
# GPU가 있으면 해당 없음 - 9,939건이 CPU 40분대에서 1~3분으로 줄어든다.
SPARE_CORES = 2

# bge-m3의 기본 최대 길이는 8192 토큰이다. 그대로 두면 6GB GPU에서 OOM이 난다
# (배치 32에 4.26GiB 단일 할당 요구). 어텐션 메모리가 길이에 제곱으로 늘기 때문이다.
#
# 실측 토큰 분포: p50=159, p90=685, p99=1877, max=5972. 2048로 끊으면 잘리는 건
# 77건(0.8%)뿐이고 전부 교수·학습(55)·내용 체계(22)다. **성취기준은 1536 초과가
# 0건**이라 주력 doc_type은 손실이 없다. 잘리는 쪽도 앞부분(프리픽스 + 본문 도입)이
# 남으므로 검색 신호는 유지된다.
MAX_SEQ_TOKENS = 2048

# GPU 배치. 2048 토큰 × 32는 OOM이라 8로 내렸다. 그래도 전체가 수 분이다.
GPU_BATCH = 8
CPU_BATCH = 16


def build(
    variant: str,
    limit: int | None = None,
    threads: int | None = None,
    device: str | None = None,
) -> np.ndarray:
    import torch
    from sentence_transformers import SentenceTransformer  # 무거워서 여기서 import

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    if device == "cpu":
        torch.set_num_threads(threads or max(1, (os.cpu_count() or 4) - SPARE_CORES))
        where = f"cpu, 스레드 {torch.get_num_threads()}개"
    else:
        where = f"{device} ({torch.cuda.get_device_name(0)})"

    rows = load_rows()[:limit]
    texts = [to_text(r, variant) for r in rows]
    print(f"{len(texts)}건 인코딩 ({MODEL_NAME}, variant={variant}, {where})")

    model = SentenceTransformer(MODEL_NAME, device=device)
    model.max_seq_length = MAX_SEQ_TOKENS
    # normalize=True면 내적이 곧 코사인 유사도가 된다 (retrieve에서 vecs @ q 한 줄).
    return model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=GPU_BATCH if device == "cuda" else CPU_BATCH,
        show_progress_bar=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="NCIC 임베딩 인덱스 생성")
    parser.add_argument("--variant", default="v2", choices=["v1", "v2", "v3"])
    parser.add_argument("--out", default=None, help="기본 vecs.npy")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--threads", type=int, default=None, help="CPU 모드에서만. 기본: 코어 수 - 2")
    parser.add_argument("--device", default=None, help="cuda | cpu. 기본: 있으면 cuda")
    args = parser.parse_args()

    vecs = build(args.variant, args.limit, args.threads, args.device)
    out = args.out or VECS
    np.save(out, vecs)
    print(f"저장: {out}  shape={vecs.shape}")


if __name__ == "__main__":
    main()
