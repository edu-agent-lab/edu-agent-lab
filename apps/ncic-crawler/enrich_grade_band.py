#!/usr/bin/env python3
"""
기존 ncic_2022_rag.jsonl을 재크롤링 없이 후처리한다.
grade_band가 비어있는 achievement_standard 레코드에 code 접두어 기반으로
유추한 학년(군)을 채우고, grade_band_source(explicit/inferred_from_code/None)를 붙인다.
"""
import json
import os

from crawl_2022_full import infer_grade_band_from_code

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "ncic_2022_rag.jsonl")


def main():
    records = [json.loads(l) for l in open(PATH, encoding="utf-8")]

    n_explicit = n_inferred = n_unmapped = 0
    for r in records:
        if r["doc_type"] != "achievement_standard":
            continue

        # 이미 한 번 이 스크립트를 돌린 적이 있으면 grade_band_source로 원래 출처를 그대로 유지한다
        # (재실행 시 grade_band가 이미 채워져 있어 "explicit"으로 잘못 재분류되는 것을 방지).
        source = r.get("grade_band_source")
        if source is None:
            if r.get("grade_band"):
                source = "explicit"
            else:
                inferred = infer_grade_band_from_code(r["code"])
                if inferred:
                    r["grade_band"] = inferred
                    source = "inferred_from_code"

        r["grade_band_source"] = source
        if source == "explicit":
            n_explicit += 1
        elif source == "inferred_from_code":
            n_inferred += 1
        else:
            n_unmapped += 1

        # text 필드도 갱신된 grade_band를 반영해 재생성한다
        r["text"] = (
            f"[{r['subject']}"
            + (f" · {r['course']}" if r["course"] else "")
            + (f" · {r['grade_band']}" if r["grade_band"] else "")
            + f" · {r['area']}]\n"
            + f"[{r['code']}] {r['content']}"
            + (f"\n(해설) {r['explanation']}" if r["explanation"] else "")
            + (f"\n(적용 시 고려 사항) {r['considerations']}" if r["considerations"] else "")
        )

    with open(PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"explicit: {n_explicit}, inferred_from_code: {n_inferred}, 매핑 안 됨: {n_unmapped}")


if __name__ == "__main__":
    main()
