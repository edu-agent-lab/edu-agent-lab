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


def fetch_lines(sess, csrf, node, openYear, retries=3):
    """view.do를 호출해 boardViewContent 줄을 가져온다. 장시간 크롤링 중에는 서버/세션
    상태에 따라 실제로는 내용이 있는데도 일시적으로 빈 응답이 오는 경우가 있어(재확인 시
    정상 응답), 비어있으면 잠깐 쉬고 재시도한다. 그래도 비면 None을 돌려준다."""
    for attempt in range(retries):
        html = fetch_view(sess, csrf, node, openYear)
        lines = extract_board_view_content(html)
        if lines:
            return lines
        if attempt < retries - 1:
            time.sleep(2.0 * (attempt + 1))
    return None


def _split_content_system_and_standards(lines):
    """단일 과목은 '가.내용체계'와 '나.성취기준'이 한 페이지에 합쳐져 오는 경우가 있다.
    '나. 성취기준' 표제를 기준으로 그 앞(내용체계)/뒤(성취기준)를 나눈다.
    표제가 없으면(이미 성취기준만 있는 페이지) 내용체계 없이 전체를 성취기준으로 본다."""
    for i, ln in enumerate(lines):
        if RE_NA.match(ln):
            return lines[:i], lines[i + 1:]
    return [], lines


def crawl_content_system_leaf(sess, csrf, node, ctx, writer, errors, lines=None):
    """'가. 내용 체계' 표(핵심 아이디어 + 범주별 내용 요소)를 크롤링한다.
    표 자체는 행/열 구조를 엄밀히 복원하지 않고, 셀 텍스트를 읽는 순서 그대로 줄 단위로
    남긴다 — 범주 라벨(지식·이해/과정·기능/가치·태도)이 텍스트 안에 그대로 있어 LLM이
    맥락으로 구조를 파악하는 데는 충분하고, HTML rowspan/colspan을 엄밀히 복원하는 것보다
    훨씬 견고하다."""
    if lines is None:
        # 단독 리프(예: "가. 내용 체계 - 공통수학1")는 그 자체가 내용체계 표뿐이고
        # '나.성취기준' 표제가 같은 페이지에 없으므로, 결합페이지처럼 나눌 필요 없이 전체를 쓴다.
        time.sleep(SLEEP)
        try:
            lines = fetch_lines(sess, csrf, node, ctx["openYear"])
            if not lines:
                errors.append({"ctx": ctx, "node": node["title"], "error": "boardViewContent 없음"})
                return
        except Exception as e:
            errors.append({"ctx": ctx, "node": node["title"], "error": str(e)})
            return

    if not lines:
        return

    m = RE_GA.match(node["title"])
    course = ctx["course"]
    if m:
        specific = re.sub(r"^가\.\s*내용\s*체계\s*-\s*", "", node["title"]).strip()
        if specific and specific != node["title"]:
            course = specific

    record = {
        "doc_type": "content_system",
        "school_level": ctx["school_level"],
        "subject": ctx["subject"],
        "course": course,
        "seq": node.get("ref"),
        "lines": lines,
        "text": (
            f"[{ctx['subject']}" + (f" · {course}" if course else "") + " · 내용 체계]\n"
            + "\n".join(lines)
        ),
    }
    writer(record)


def crawl_purpose_goals_leaf(sess, csrf, node, ctx, writer, errors):
    """'1. 성격 및 목표' 페이지: 가.성격 / 나.목표 두 섹션을 텍스트로 남긴다."""
    time.sleep(SLEEP)
    try:
        lines = fetch_lines(sess, csrf, node, ctx["openYear"])
        if not lines:
            errors.append({"ctx": ctx, "node": node["title"], "error": "boardViewContent 없음"})
            return
        sections = structure_teaching_assessment(lines)  # 가/나 최상위 분리 로직을 그대로 재사용
    except Exception as e:
        errors.append({"ctx": ctx, "node": node["title"], "error": str(e)})
        return

    for top, subs in sections.items():
        merged_text = "\n".join(v["text"] for v in subs.values())
        record = {
            "doc_type": "purpose_goals",
            "school_level": ctx["school_level"],
            "subject": ctx["subject"],
            "course": ctx["course"],
            "section": top,  # "성격" | "목표"
            "seq": node.get("ref"),
            "text": (
                f"[{ctx['subject']}" + (f" · {ctx['course']}" if ctx["course"] else "")
                + f" · {top}]\n" + merged_text
            ),
        }
        writer(record)


def crawl_achievement_leaf(sess, csrf, node, ctx, writer, errors):
    time.sleep(SLEEP)
    try:
        raw_lines = fetch_lines(sess, csrf, node, ctx["openYear"])
        if not raw_lines:
            errors.append({"ctx": ctx, "node": node["title"], "error": "boardViewContent 없음"})
            return
        content_system_lines, standards_lines = _split_content_system_and_standards(raw_lines)
        units = structure_standards(standards_lines)
    except Exception as e:
        errors.append({"ctx": ctx, "node": node["title"], "error": str(e)})
        return

    # 단일 과목 페이지는 '가.내용체계'가 같은 페이지에 합쳐져 있으므로 같은 fetch에서 같이 뽑는다
    # (별도 리프로 존재하는 경우는 walk()에서 crawl_content_system_leaf를 따로 호출한다).
    if content_system_lines:
        crawl_content_system_leaf(sess, csrf, node, ctx, writer, errors, lines=content_system_lines)

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
        lines = fetch_lines(sess, csrf, node, ctx["openYear"])
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
                crawl_content_system_leaf(sess, csrf, child, ctx, writer, errors)
            else:
                walk_achievement_branch(sess, csrf, child, ctx, writer, errors)
        return

    if RE_1.match(title):
        crawl_purpose_goals_leaf(sess, csrf, node, ctx, writer, errors)
        return

    if "개요" in title:
        return  # '교육과정 설계의 개요'는 1.성격및목표와 내용이 겹치고 포맷도 달라(HWP JSON) 스킵

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
