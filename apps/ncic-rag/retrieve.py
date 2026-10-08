"""질문 -> NCIC 근거 Top-K. (Retrieval)

    python retrieve.py "중학교 사회에서 환경 문제로 토론할 때 성취기준"
    python retrieve.py "..." --mode dense      # 벡터만
    python retrieve.py "..." --mode bm25       # 키워드만
    python retrieve.py "..." --doc-type achievement_standard --school-level 중학교

세 방식을 한 파일에 둔 이유: 전략 문서가 요구하는 비교(Vector vs Hybrid)를 같은
필터·같은 랭킹 아래에서 재야 하기 때문이다. --mode만 바꿔 돌린다.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np

from dataset import MODEL_NAME, VECS, load_rows, to_text

# doc_type별 가중치. 성취기준 3,294건 vs 서술 문서 4,075건이 한 인덱스에 있어
# "환경 토론" 같은 질의에 과목 성격/목표 문서가 올라올 수 있다. 기본은 전부 1.0으로
# 두고(= 끄고), 질의셋에서 성취기준이 밀리는 게 보이면 여기서 내린다.
# doc_type별 가중치. 성취기준 5,709건과 서술 문서 4,075건이 한 인덱스에 있어서,
# "체육 안전 지도" 같은 질의에 교수·학습 지침이 성취기준보다 위로 온다(실측 3건).
# 점수 차가 0.008~0.026으로 작아 10%만 깎아도 뒤집힌다.
#
# 골든셋 22건 기준 비성취기준 가중치: 1.0 -> Top1 7/13, 0.95 -> 9/13, 0.9 -> 10/13.
# 0.8까지 내려도 더 좋아지지 않고 노이즈만 늘어 0.9로 정했다.
STANDARD_BONUS = 0.9  # 성취기준이 아닌 doc_type에 곱하는 값

WEIGHT = {
    "achievement_standard": 1.0,
    "content_system": STANDARD_BONUS,
    "purpose_goals": STANDARD_BONUS,
    "teaching_assessment": STANDARD_BONUS,
}

# BM25 점수는 스케일이 제멋대로(0~30)라 코사인(0~1)과 그냥 더할 수 없다.
# 각자 최대값으로 나눠 0~1로 맞춘 뒤 이 비율로 섞는다.
#
# 골든셋 22건 스윕: 0.7 -> Top1 8/13 · 통과 12, 0.4 -> 9/13 · 12, 0.15 -> 11/13 · 14.
# BM25는 순위를 정하는 주력이 아니라 dense가 놓친 정확 어휘(성취기준 코드, "갯벌")를
# 끌어올리는 보조라서 비중이 낮을 때 가장 좋다. 0.10~0.20이 평평해 중간값을 쓴다.
BM25_WEIGHT = 0.15

# filter_mode="soft"에서 조건에 안 맞는 레코드의 점수에 곱하는 값.
# 1.0이면 필터를 안 거는 것과 같고, 0이면 hard와 같다.
FILTER_PENALTY = 0.5

_TOKEN = re.compile(r"[가-힣A-Za-z0-9]+")
_HANGUL = re.compile(r"[가-힣]")


def tokenize(text: str) -> list[str]:
    """어절 + 한글 문자 2-gram.

    어절만 쓰면 조사가 붙은 "저작권을"이 "저작권"과 다른 토큰이 되어 못 걸린다.
    실제로 골든셋 lexical-03("저작권")이 6건 중 0건이었다. 2-gram을 더하면
    "저작권을" -> 저작,작권,권을 / "저작권" -> 저작,작권 으로 겹친다.

    형태소 분석기(kiwipiepy) 없이 이걸로 BM25 R@10이 0.53 -> 0.79, hybrid가
    0.78 -> 0.85로 올랐다. 분석기는 이 방식으로 부족한 게 나올 때 붙인다.
    """
    out = []
    for word in _TOKEN.findall(text.lower()):
        out.append(word)
        if len(word) > 1 and _HANGUL.match(word):
            out += [word[i : i + 2] for i in range(len(word) - 1)]
    return out


class Index:
    def __init__(self, variant: str = "v2", vecs_path=VECS) -> None:
        self.rows = load_rows()
        self.variant = variant
        # vecs.npy가 없어도 --mode bm25는 돌아간다. 인덱싱이 끝나기 전에
        # 파이프라인과 골든셋을 먼저 검증하려고 이렇게 뒀다.
        self.vecs = np.load(vecs_path) if Path(vecs_path).exists() else None
        if self.vecs is not None and len(self.vecs) != len(self.rows):
            raise SystemExit(
                f"vecs({len(self.vecs)})와 rows({len(self.rows)}) 길이가 다릅니다. "
                "JSONL이 바뀌었으면 index.py를 다시 돌리세요."
            )
        self._model = None
        self._bm25 = None

    # 둘 다 무겁고 mode에 따라 하나만 필요해서 쓸 때 만든다.
    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(MODEL_NAME)
        return self._model

    @property
    def bm25(self):
        if self._bm25 is None:
            from rank_bm25 import BM25Okapi

            self._bm25 = BM25Okapi(
                [tokenize(to_text(r, self.variant)) for r in self.rows]
            )
        return self._bm25

    def search(
        self,
        query: str,
        *,
        mode: str = "hybrid",
        top_k: int = 5,
        doc_type: str | None = None,
        school_level: str | None = None,
        subject: str | None = None,
        course: str | None = None,
        filter_mode: str = "hard",
    ) -> list[tuple[dict, float]]:
        score = np.zeros(len(self.rows))

        if mode in ("dense", "hybrid"):
            if self.vecs is None:
                raise SystemExit(
                    f"{mode} 모드에는 vecs.npy가 필요합니다. index.py를 먼저 돌리세요."
                )
            q = self.model.encode(query, normalize_embeddings=True)
            score = score + self.vecs @ q  # normalize 했으므로 내적 = 코사인

        if mode in ("bm25", "hybrid"):
            raw = np.asarray(self.bm25.get_scores(tokenize(query)))
            if raw.max() > 0:
                raw = raw / raw.max()
            score = score + (BM25_WEIGHT if mode == "hybrid" else 1.0) * raw

        score = score * np.array([WEIGHT[r["doc_type"]] for r in self.rows])

        # 메타데이터 필터. 학교급·과목은 "비슷하면 통과"가 아니라 맞거나 틀린
        # 조건이라 유사도에 맡기면 안 된다 - 실측으로 "중2" 질의에 고등학교
        # 성취기준이 3·4위에 섞였고, 점수대(중 0.626/0.607, 고 0.570/0.555)가
        # 겹쳐서 벡터가 학교급을 강제하지 못한다.
        #
        # 적용 방식은 둘 다 둔다. 어느 쪽이 나은지는 질의셋으로 재야 한다.
        #   hard: 안 맞으면 후보에서 제외 (조건을 어기지 않지만 0건이 날 수 있다)
        #   soft: 안 맞으면 점수에 FILTER_PENALTY를 곱한다 (0건을 피하지만 섞인다)
        mismatch = np.zeros(len(self.rows), dtype=bool)
        for field, wanted in (
            ("doc_type", doc_type),
            ("school_level", school_level),
            ("subject", subject),
            ("course", course),
        ):
            if wanted:
                mismatch |= ~np.array(
                    [wanted in str(r.get(field) or "") for r in self.rows]
                )
        if filter_mode == "soft":
            score[mismatch] *= FILTER_PENALTY
        else:
            score[mismatch] = -np.inf

        order = np.argsort(score)[::-1][:top_k]
        return [(self.rows[i], float(score[i])) for i in order if score[i] > -np.inf]


def main() -> None:
    parser = argparse.ArgumentParser(description="NCIC 검색")
    parser.add_argument("query")
    parser.add_argument("--mode", default="hybrid", choices=["dense", "bm25", "hybrid"])
    parser.add_argument("--variant", default="v2", choices=["v1", "v2", "v3"])
    parser.add_argument("--vecs", default=VECS)
    parser.add_argument("-k", "--top-k", type=int, default=5)
    parser.add_argument("--doc-type")
    parser.add_argument("--school-level")
    parser.add_argument("--subject")
    parser.add_argument("--course")
    parser.add_argument("--filter-mode", default="hard", choices=["hard", "soft"])
    args = parser.parse_args()

    index = Index(args.variant, args.vecs)
    hits = index.search(
        args.query,
        mode=args.mode,
        top_k=args.top_k,
        doc_type=args.doc_type,
        school_level=args.school_level,
        subject=args.subject,
        course=args.course,
        filter_mode=args.filter_mode,
    )

    print(f"\n[{args.mode}] {args.query}\n" + "-" * 70)
    for rank, (row, s) in enumerate(hits, 1):
        code = row.get("code") or row["doc_type"]
        where = " · ".join(
            str(row[f]) for f in ("school_level", "subject", "course") if row.get(f)
        )
        body = (row.get("content") or row["text"]).replace("\n", " ")
        print(f"{rank}. [{s:.3f}] {code}  ({where})")
        print(f"   {body[:120]}")
    print()


if __name__ == "__main__":
    main()
