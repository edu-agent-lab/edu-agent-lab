"""ncic-crawler가 만든 ncic_2022_rag.jsonl을 읽어서 검색 실험에 쓸 레코드 목록으로 만든다."""
import json
import os

DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "ncic-crawler", "output", "ncic_2022_rag.jsonl"
)


def load_records(path=DEFAULT_PATH, doc_type=None):
    """doc_type을 주면 그 타입만(예: "achievement_standard") 필터링해서 반환한다.
    각 레코드에 원본 파일 기준 줄 번호를 "_id"로 붙여준다(임베딩 캐시와 매칭용)."""
    records = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            r = json.loads(line)
            if doc_type is not None and r.get("doc_type") != doc_type:
                continue
            r["_id"] = i
            records.append(r)
    return records


def filter_by_slots(records, school_level=None, subject=None, grade_band=None):
    """학년/과목 슬롯으로 1차 필터링 (정확 매칭)."""
    out = records
    if school_level:
        out = [r for r in out if r.get("school_level") == school_level]
    if subject:
        out = [r for r in out if r.get("subject") == subject]
    if grade_band:
        out = [r for r in out if r.get("grade_band") == grade_band]
    return out
