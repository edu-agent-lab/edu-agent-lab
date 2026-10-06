"""JSONL 전체를 bge-m3-ko로 임베딩해 vecs.npy에 저장한다. (Indexing)

    python index.py            # v2로 전체 임베딩 -> vecs.npy
    python index.py --variant v3 --out vecs_v3.npy
    python index.py --limit 50 # 연결·형태 확인용 (모델 다운로드 포함 첫 실행 점검)

행 순서 = dataset.load_rows() 순서 = JSONL 파일 순서. retrieve.py가 이 순서로
번호를 되짚으므로 JSONL이 바뀌면 다시 돌려야 한다.
"""

from __future__ import annotations

import argparse

import numpy as np

from dataset import MODEL_NAME, VECS, load_rows, to_text


def build(variant: str, limit: int | None = None) -> np.ndarray:
    from sentence_transformers import SentenceTransformer  # 무거워서 여기서 import

    rows = load_rows()[:limit]
    texts = [to_text(r, variant) for r in rows]
    print(f"{len(texts)}건 인코딩 ({MODEL_NAME}, variant={variant})")

    model = SentenceTransformer(MODEL_NAME)
    # normalize=True면 내적이 곧 코사인 유사도가 된다 (retrieve에서 vecs @ q 한 줄).
    return model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=16,
        show_progress_bar=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="NCIC 임베딩 인덱스 생성")
    parser.add_argument("--variant", default="v2", choices=["v1", "v2", "v3"])
    parser.add_argument("--out", default=None, help="기본 vecs.npy")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    vecs = build(args.variant, args.limit)
    out = args.out or VECS
    np.save(out, vecs)
    print(f"저장: {out}  shape={vecs.shape}")


if __name__ == "__main__":
    main()
