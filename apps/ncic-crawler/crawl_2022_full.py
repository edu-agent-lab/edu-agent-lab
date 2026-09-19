#!/usr/bin/env python3
"""
2022 개정 교육과정(degreeCode=1014) 전 학교급 · 전 과목의
"2. 내용 체계 및 성취기준" + "3. 교수·학습 및 평가"를 재귀적으로 크롤링해
RAG용 JSONL로 저장한다.

범위: 초·중·고·초중등학교(통합)·특수교육, 각 학교급의 2022.12 원본
     (단, 초중등학교(통합)은 2022.12 판이 없어 최초 판인 2024.08 사용)
"""
import json
import os
import re
import sys
import time

from ncic_crawl import (
    Session, get_csrf, node_list,
    extract_board_view_content, structure_standards, structure_teaching_assessment,
)

SLEEP = 0.15  # 서버 부하를 고려한 요청 간 지연(초)
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "ncic_2022_rag.jsonl")
ERR_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "ncic_2022_errors.jsonl")

SCHOOL_LEVELS = [
    ("1002", "2022", "12", "초등학교"),
    ("1003", "2022", "12", "중학교"),
    ("1004", "2022", "12", "고등학교"),
    ("1016", "2024", "08", "초중등학교(통합)"),  # 2022.12 판 없음 -> 최초 판 사용
    ("1038", "2022", "12", "특수교육"),
]

RE_1 = re.compile(r"^1\.\s*성격")
RE_2 = re.compile(r"^2\.\s*내용\s*체계")
RE_3 = re.compile(r"^3\.\s*교수")
RE_GA = re.compile(r"^가\.\s*내용\s*체계")
RE_NA = re.compile(r"^나\.\s*성취기준")

# 성취기준 코드 앞자리 숫자 -> 학년(군). 2015 개정부터 이어진 국가교육과정 코드 표기 관행으로,
# 이번에 크롤링한 NCIC 데이터 자체에서 "이게 그 뜻이다"라고 명시한 근거를 찾지는 못했다
# (초등학교 2/4/6은 실제 학년군 브라켓과 대조해 확인함, 9/10/12는 일반적으로 알려진 관례).
CODE_PREFIX_GRADE = {
    "2": "초등학교 1~2학년",
    "4": "초등학교 3~4학년",
    "6": "초등학교 5~6학년",
    "9": "중학교 1~3학년",
    "10": "고등학교 공통과목(1학년)",
    "12": "고등학교 선택과목(2~3학년)",
}
CODE_PREFIX_RE = re.compile(r"^0*(\d+)")


def infer_grade_band_from_code(code):
    m = CODE_PREFIX_RE.match(code)
    if not m:
        return None
    return CODE_PREFIX_GRADE.get(m.group(1))


def get_children(sess, node):
    return node_list(
        sess,
        type="ogi4", nowTblType="org", menuType="1", isAdmin="0",
        invDepth=node.get("invDepth", 1),
        degreeCode=node.get("degreeCode", ""),
        classCode=node.get("classCode", ""),
        subjectCode=node.get("subjectCode", ""),
        subjectDefCode=node.get("subjectDefCode", ""),
        openYear=node.get("openYear", ""),
        openMonth=node.get("openMonth", ""),
        ref=node.get("ref", "0"),
    )


def fetch_view(sess, csrf, node, openYear):
    return sess.post("/inv/org/view.do", {
        "_csrf": csrf,
        "openYear": openYear,
        "seq": node.get("ref", ""),
        "location": "",
        "orgType": "ogi4",
        "menuType": "1",
        "nationCd": "1000",
    })


def _standards_lines_only(lines):
    """단일 과목은 '가.내용체계'와 '나.성취기준'이 한 페이지에 합쳐져 오는 경우가 있다.
    '나. 성취기준' 표제가 있으면 그 이후만, 없으면(이미 성취기준만 있는 페이지) 전체를 쓴다."""
    for i, ln in enumerate(lines):
        if RE_NA.match(ln):
            return lines[i + 1:]
    return lines


def crawl_achievement_leaf(sess, csrf, node, ctx, writer, errors):
    time.sleep(SLEEP)
    try:
        html = fetch_view(sess, csrf, node, ctx["openYear"])
        lines = extract_board_view_content(html)
        if not lines:
            errors.append({"ctx": ctx, "node": node["title"], "error": "boardViewContent 없음"})
            return
        units = structure_standards(_standards_lines_only(lines))
    except Exception as e:
        errors.append({"ctx": ctx, "node": node["title"], "error": str(e)})
        return

    explicit_grade_band = node["title"] if node["title"].startswith("[") else None

    # 부모 폴더가 "공통수학1, 공통수학2"처럼 여러 과목을 묶고 있어도,
    # 리프 제목이 "나. 성취기준 - 공통수학1"이면 그 과목명으로 course를 좁힌다.
    m = RE_NA.match(node["title"])
    course = ctx["course"]
    if m:
        specific = re.sub(r"^나\.\s*성취기준\s*-\s*", "", node["title"]).strip()
        if specific and specific != node["title"]:
            course = specific
    ctx = dict(ctx, course=course)

    for u in units:
        for std in u["standards"]:
            if explicit_grade_band:
                grade_band, grade_band_source = explicit_grade_band, "explicit"
            else:
                inferred = infer_grade_band_from_code(std["code"])
                grade_band, grade_band_source = inferred, ("inferred_from_code" if inferred else None)

            record = {
                "doc_type": "achievement_standard",
                "school_level": ctx["school_level"],
                "subject": ctx["subject"],
                "course": ctx["course"],
                "grade_band": grade_band,
                "grade_band_source": grade_band_source,
                "area": u["unit_title"],
                "code": std["code"],
                "content": std["content"],
                "explanation": std["explanation"],
                "considerations": u["considerations"],
                "seq": node.get("ref"),
                "text": (
                    f"[{ctx['subject']}"
                    + (f" · {ctx['course']}" if ctx["course"] else "")
                    + (f" · {grade_band}" if grade_band else "")
                    + f" · {u['unit_title']}]\n"
                    + f"[{std['code']}] {std['content']}"
                    + (f"\n(해설) {std['explanation']}" if std["explanation"] else "")
                    + (f"\n(적용 시 고려 사항) {u['considerations']}" if u["considerations"] else "")
                ),
            }
            writer(record)


def crawl_teaching_assessment_leaf(sess, csrf, node, ctx, writer, errors):
    time.sleep(SLEEP)
    try:
        html = fetch_view(sess, csrf, node, ctx["openYear"])
        lines = extract_board_view_content(html)
        if not lines:
            errors.append({"ctx": ctx, "node": node["title"], "error": "boardViewContent 없음"})
            return
        sections = structure_teaching_assessment(lines)
    except Exception as e:
        errors.append({"ctx": ctx, "node": node["title"], "error": str(e)})
        return

    for top, subs in sections.items():
        for sub, v in subs.items():
            record = {
                "doc_type": "teaching_assessment",
                "school_level": ctx["school_level"],
                "subject": ctx["subject"],
                "course": ctx["course"],
                "top": top,
                "sub": sub,
                "seq": node.get("ref"),
                "text": (
                    f"[{ctx['subject']}"
                    + (f" · {ctx['course']}" if ctx["course"] else "")
                    + f" · {top} · {sub}]\n" + v["text"]
                ),
            }
            writer(record)


def walk_achievement_branch(sess, csrf, node, ctx, writer, errors):
    """'나. 성취기준' 하위: leaf면 바로 크롤링, folder면(학년군 분할) 재귀."""
    if node.get("folder"):
        time.sleep(SLEEP)
        try:
            children = get_children(sess, node)
        except Exception as e:
            errors.append({"ctx": ctx, "node": node["title"], "error": str(e)})
            return
        for child in children:
            walk_achievement_branch(sess, csrf, child, ctx, writer, errors)
    else:
        crawl_achievement_leaf(sess, csrf, node, ctx, writer, errors)


def walk(sess, csrf, node, ctx, writer, errors):
    title = node["title"]

    if RE_3.match(title):
        if node.get("folder"):
            time.sleep(SLEEP)
            try:
                children = get_children(sess, node)
            except Exception as e:
                errors.append({"ctx": ctx, "node": title, "error": str(e)})
                return
            for child in children:
                if not child.get("folder"):
                    crawl_teaching_assessment_leaf(sess, csrf, child, ctx, writer, errors)
                else:
                    walk(sess, csrf, child, ctx, writer, errors)
        else:
            crawl_teaching_assessment_leaf(sess, csrf, node, ctx, writer, errors)
        return

    if RE_2.match(title):
        if not node.get("folder"):
            # 단일 과목: '가.내용체계'+'나.성취기준'이 한 페이지에 합쳐져 있음
            crawl_achievement_leaf(sess, csrf, node, ctx, writer, errors)
            return
        time.sleep(SLEEP)
        try:
            children = get_children(sess, node)
        except Exception as e:
            errors.append({"ctx": ctx, "node": title, "error": str(e)})
            return
        for child in children:
            if RE_GA.match(child["title"]):
                continue  # 내용 체계 표는 성취기준 크롤링 목적상 스킵
            walk_achievement_branch(sess, csrf, child, ctx, writer, errors)
        return

    if RE_1.match(title) or "개요" in title:
        return  # 성격/목표, 설계 개요는 스킵

    if node.get("folder"):
        time.sleep(SLEEP)
        try:
            children = get_children(sess, node)
        except Exception as e:
            errors.append({"ctx": ctx, "node": title, "error": str(e)})
            return
        new_ctx = dict(ctx, course=title)
        for child in children:
            walk(sess, csrf, child, new_ctx, writer, errors)
        return

    # 그 외 leaf (매칭 안 되는 것들)는 스킵


def main():
    sess = Session()
    list_html = sess.get("/inv/org/list.do")
    csrf = get_csrf(list_html)
    if not csrf:
        print("CSRF 토큰을 찾지 못했습니다", file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    out_f = open(OUT_PATH, "w", encoding="utf-8")
    errors = []
    count = [0]

    def writer(record):
        out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
        out_f.flush()
        count[0] += 1

    for classCode, openYear, openMonth, school_level in SCHOOL_LEVELS:
        print(f"=== {school_level} (classCode={classCode}, {openYear}.{openMonth}) ===", flush=True)
        root = {"invDepth": 3, "degreeCode": "1014", "classCode": classCode,
                "openYear": openYear, "openMonth": openMonth}
        try:
            subjects = get_children(sess, root)
        except Exception as e:
            errors.append({"ctx": {"school_level": school_level}, "node": "root", "error": str(e)})
            continue
        time.sleep(SLEEP)

        for subj in subjects:
            print(f"  - {subj['title']} ...", flush=True)
            ctx = {
                "school_level": school_level,
                "subject": subj["title"],
                "course": None,
                "openYear": openYear,
            }
            walk(sess, csrf, subj, ctx, writer, errors)
            print(f"    누적 레코드 {count[0]}건", flush=True)

    out_f.close()

    with open(ERR_PATH, "w", encoding="utf-8") as ef:
        for e in errors:
            ef.write(json.dumps(e, ensure_ascii=False) + "\n")

    print(f"\n완료: 총 {count[0]}건 저장 -> {OUT_PATH}")
    print(f"에러 {len(errors)}건 -> {ERR_PATH}")


if __name__ == "__main__":
    main()
