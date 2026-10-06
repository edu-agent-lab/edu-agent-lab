"""ncic_2022_rag.jsonl 로드 + 임베딩 입력 문자열 생성.

index.py와 retrieve.py가 같은 순서·같은 정규화를 봐야 하므로 여기 모아둔다.
JSONL 전체(9,784건, doc_type 4종)를 다 쓴다 - 필터링은 검색 단계에서 한다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

APP_DIR = Path(__file__).parent
JSONL = APP_DIR.parent / "ncic-crawler" / "output" / "ncic_2022_rag.jsonl"
VECS = APP_DIR / "vecs.npy"

MODEL_NAME = "dragonkue/BGE-m3-ko"

# 크롤러가 `[9사(지리)01-01]은 ...`에서 코드만 떼어내 해설이 조사로 시작하는 경우가
# 964건 있다. 임베딩에는 영향이 미미하지만 프롬프트에 그대로 나가면 문장이 깨진다.
_DANGLING = re.compile(r"^[은는이가을를의도]\s+")


def load_rows() -> list[dict]:
    """JSONL을 파일 순서 그대로 읽는다. 이 순서가 vecs.npy의 행 번호다."""
    rows = [json.loads(line) for line in JSONL.open(encoding="utf-8") if line.strip()]
    for row in rows:
        if row.get("explanation"):
            row["explanation"] = _DANGLING.sub("", row["explanation"])
    return rows


def _head(row: dict, *fields: str) -> str:
    """메타데이터 프리픽스. 질의에 과목·학년이 섞여 들어오므로 본문 앞에 붙인다."""
    return " ".join(str(row[f]) for f in fields if row.get(f))


def to_text(row: dict, variant: str = "v2") -> str:
    """임베딩에 넣을 문자열.

    성취기준만 variant로 갈린다. considerations(= text에 포함)는 성취기준별이 아니라
    **영역 공통** 텍스트라, 같은 영역 성취기준 5건에 같은 500자가 붙는다. 그대로
    임베딩하면 그 영역 안에서 순위 변별이 무너진다. 어느 쪽이 나은지는 질의셋으로
    재야 하므로 셋을 다 남겨둔다.

        v1 = content만            변별 최대, 어휘 최소
        v2 = content + explanation  (기본)
        v3 = text 전체             considerations까지. 수업 방법 어휘가 여기 있다

    나머지 doc_type은 text가 곧 본문이고 중복이 없어 통째로 넣는다.
    """
    dt = row["doc_type"]

    if dt == "achievement_standard":
        head = _head(row, "school_level", "subject", "course", "grade_band", "area")
        if variant == "v3":
            return f"{head}\n{row['text']}"
        body = f"[{row['code']}] {row['content']}"
        if variant == "v2" and row.get("explanation"):
            body += f"\n{row['explanation']}"
        return f"{head}\n{body}"

    if dt == "purpose_goals":
        head = _head(row, "school_level", "subject", "course", "section")
    elif dt == "teaching_assessment":
        head = _head(row, "school_level", "subject", "course", "top", "sub")
    else:  # content_system
        head = _head(row, "school_level", "subject", "course")

    return f"{head}\n{row['text']}"
