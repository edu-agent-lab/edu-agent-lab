#!/usr/bin/env python3
"""
ncic_2022_errors.jsonl에 실패로 기록된 (school_level, subject) 조합만 골라
다시 크롤링한다. 재시도 3회까지 다 실패했던 항목들인데, 개별로 다시 열어보면
멀쩡히 열리는 경우가 많다(대량 크롤링 중 세션/부하로 인한 일시적 실패로 보임) —
그래서 전체 재크롤 대신 실패한 과목만 다시 돈다.

결과는 output/ncic_2022_rag.jsonl에 병합(해당 과목의 기존 레코드를 지우고 새로 채움).
"""
import json
import os

from ncic_crawl import Session, get_csrf
from crawl_2022_full import get_children, walk, SCHOOL_LEVELS

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
MAIN_PATH = os.path.join(OUT_DIR, "ncic_2022_rag.jsonl")
ERR_PATH = os.path.join(OUT_DIR, "ncic_2022_errors.jsonl")

LEVEL_TO_PARAMS = {level: (classCode, openYear, openMonth)
                   for classCode, openYear, openMonth, level in SCHOOL_LEVELS}


def affected_subjects():
    pairs = set()
    with open(ERR_PATH, encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            level = e["ctx"].get("school_level")
            subject = e["ctx"].get("subject")
            if level and subject:
                pairs.add((level, subject))
    return sorted(pairs)


def main():
    targets = affected_subjects()
    print(f"재크롤 대상: {len(targets)}개 과목")
    for t in targets:
        print(" -", t)

    sess = Session()
    list_html = sess.get("/inv/org/list.do")
    csrf = get_csrf(list_html)
    if not csrf:
        raise RuntimeError("CSRF 토큰을 찾지 못했습니다")

    new_records, errors = [], []

    def writer(record):
        new_records.append(record)

    for school_level, subject_title in targets:
        classCode, openYear, openMonth = LEVEL_TO_PARAMS[school_level]
        root = {"invDepth": 3, "degreeCode": "1014", "classCode": classCode,
                "openYear": openYear, "openMonth": openMonth}
        try:
            subjects = get_children(sess, root)
        except Exception as e:
            errors.append({"ctx": {"school_level": school_level, "subject": subject_title},
                            "node": "root", "error": str(e)})
            continue

        subj = next((s for s in subjects if s["title"] == subject_title), None)
        if subj is None:
            print(f"  !! {school_level}/{subject_title} 과목을 트리에서 못 찾음", flush=True)
            continue

        print(f"  - {school_level} {subject_title} ...", flush=True)
        n_before = len(new_records)
        ctx = {"school_level": school_level, "subject": subject_title,
               "course": None, "openYear": openYear}
        walk(sess, csrf, subj, ctx, writer, errors)
        print(f"    {len(new_records) - n_before}건", flush=True)

    replace_keys = set(targets)
    old_records = []
    with open(MAIN_PATH, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if (r["school_level"], r["subject"]) in replace_keys:
                continue
            old_records.append(r)

    merged = old_records + new_records
    with open(MAIN_PATH, "w", encoding="utf-8") as f:
        for r in merged:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(ERR_PATH, "w", encoding="utf-8") as ef:
        for e in errors:
            ef.write(json.dumps(e, ensure_ascii=False) + "\n")

    print(f"\n병합 완료: 총 {len(merged)}건 (신규 {len(new_records)}건) -> {MAIN_PATH}")
    print(f"남은 에러 {len(errors)}건 -> {ERR_PATH}")


if __name__ == "__main__":
    main()
