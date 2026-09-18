#!/usr/bin/env python3
"""
crawl_2022_full.py 실행 중 와이파이 단절(curl code=6)로 누락된 부분을 재크롤링한다.
- 초중등학교(통합), 특수교육: 통째로 누락 (root 호출 자체가 실패)
- 고등학교 전문 교과: 중간(융복합·지식 재산)에서 끊김 -> 통째로 재크롤 후 기존 부분 교체
- 고등학교 한국어 교육과정/창의적 체험활동: 다른 학교급에서도 0건이라 낮은 우선순위지만 확인차 포함

결과는 output/ncic_2022_rag.jsonl 에 병합한다(기존 전문교과 레코드는 제거 후 새로 채움).
"""
import json
import os

from ncic_crawl import Session, get_csrf
from crawl_2022_full import get_children, walk

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
MAIN_PATH = os.path.join(OUT_DIR, "ncic_2022_rag.jsonl")
RESUME_LOG = os.path.join(OUT_DIR, "ncic_2022_resume_errors.jsonl")

# (classCode, openYear, openMonth, school_level, subjects_filter)
# subjects_filter=None -> 학교급 전체 과목 크롤
TARGETS = [
    ("1016", "2024", "08", "초중등학교(통합)", None),
    ("1038", "2022", "12", "특수교육", None),
    ("1004", "2022", "12", "고등학교", {"전문 교과", "한국어 교육과정", "창의적 체험활동"}),
]

# 이번에 다시 채우는 (school_level, subject) 조합은 기존 레코드를 지우고 새로 넣는다
REPLACE_KEYS = {("고등학교", s) for s in ["전문 교과", "한국어 교육과정", "창의적 체험활동"]}
REPLACE_KEYS |= {("초중등학교(통합)", None)}  # None = 학교급 전체
REPLACE_KEYS |= {("특수교육", None)}


def main():
    sess = Session()
    list_html = sess.get("/inv/org/list.do")
    csrf = get_csrf(list_html)
    if not csrf:
        raise RuntimeError("CSRF 토큰을 찾지 못했습니다")

    new_records = []
    errors = []

    def writer(record):
        new_records.append(record)

    for classCode, openYear, openMonth, school_level, subjects_filter in TARGETS:
        print(f"=== {school_level} (classCode={classCode}, {openYear}.{openMonth}) ===", flush=True)
        root = {"invDepth": 3, "degreeCode": "1014", "classCode": classCode,
                "openYear": openYear, "openMonth": openMonth}
        try:
            subjects = get_children(sess, root)
        except Exception as e:
            errors.append({"school_level": school_level, "node": "root", "error": str(e)})
            print(f"  !! root 호출 실패: {e}", flush=True)
            continue

        for subj in subjects:
            if subjects_filter is not None and subj["title"] not in subjects_filter:
                continue
            print(f"  - {subj['title']} ...", flush=True)
            n_before = len(new_records)
            ctx = {"school_level": school_level, "subject": subj["title"],
                   "course": None, "openYear": openYear}
            walk(sess, csrf, subj, ctx, writer, errors)
            print(f"    {len(new_records) - n_before}건", flush=True)

    print(f"\n신규 레코드 {len(new_records)}건, 에러 {len(errors)}건", flush=True)

    # 기존 파일에서 이번에 재크롤한 (school_level, subject) 레코드는 제거
    old_records = []
    if os.path.exists(MAIN_PATH):
        with open(MAIN_PATH, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                key_specific = (r["school_level"], r["subject"])
                key_wholelevel = (r["school_level"], None)
                if key_specific in REPLACE_KEYS or key_wholelevel in REPLACE_KEYS:
                    continue
                old_records.append(r)

    merged = old_records + new_records
    with open(MAIN_PATH, "w", encoding="utf-8") as f:
        for r in merged:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(RESUME_LOG, "w", encoding="utf-8") as ef:
        for e in errors:
            ef.write(json.dumps(e, ensure_ascii=False) + "\n")

    print(f"병합 완료: 총 {len(merged)}건 -> {MAIN_PATH}")
    print(f"이번 재크롤 에러 {len(errors)}건 -> {RESUME_LOG}")


if __name__ == "__main__":
    main()
