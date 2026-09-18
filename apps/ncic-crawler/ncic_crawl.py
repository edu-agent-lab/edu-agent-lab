#!/usr/bin/env python3
"""
NCIC(국가교육과정정보센터) 원문 인벤토리 - 성취기준 크롤러
https://ncic.re.kr/inv/org/list.do 의 "보기" 팝업 내용을 크롤링한다.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
from html.parser import HTMLParser

BASE = "https://ncic.re.kr"
UA = "Mozilla/5.0 (compatible; ncic-crawler/1.0)"


class Session:
    """urllib이 로컬 환경의 SSL 신뢰 체인 문제로 실패하는 경우가 있어 curl을 사용한다."""

    def __init__(self):
        self.cookiejar = tempfile.NamedTemporaryFile(prefix="ncic_cookies_", suffix=".txt", delete=False).name

    def get(self, path, params=None):
        url = BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return self._curl(["-b", self.cookiejar, "-c", self.cookiejar, url])

    def post(self, path, data):
        url = BASE + path
        body = urllib.parse.urlencode(data)
        return self._curl(["-b", self.cookiejar, "-c", self.cookiejar, "--data", body, url])

    def _curl(self, extra_args, retries=3, backoff=2.0):
        cmd = ["curl", "-s", "-A", UA] + extra_args
        last_err = None
        for attempt in range(retries):
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode == 0:
                return result.stdout.decode("utf-8", errors="replace")
            last_err = f"curl 실패 (code={result.returncode}): {result.stderr.decode(errors='replace')}"
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
        raise RuntimeError(last_err)

    def __del__(self):
        try:
            os.unlink(self.cookiejar)
        except OSError:
            pass


def get_csrf(list_html):
    m = re.search(r'name="_csrf"\s+value="([^"]+)"', list_html)
    return m.group(1) if m else None


def node_list(sess, **params):
    params.setdefault("isAdmin", "0")
    raw = sess.post("/api/inv/inventoryNodeList.do", params)
    return json.loads(raw)


def find_leaf(sess, degreeCode, classCode, subjectCode, openYear, openMonth, target_titles, start_depth=4):
    """target_titles: 트리에서 순서대로 클릭해 내려갈 title 목록 (부분일치)
    start_depth=4 는 subjectCode(예: 수학)가 이미 정해진 상태에서 그 하위 항목부터 탐색함을 의미한다."""
    depth = start_depth
    ref = None
    node = None
    common = dict(type="ogi4", nowTblType="org", menuType="1",
                  degreeCode=degreeCode, classCode=classCode, subjectCode=subjectCode,
                  openYear=openYear, openMonth=openMonth)

    nodes = node_list(sess, invDepth=depth, **common)
    for title in target_titles:
        match = next((n for n in nodes if title in n["title"]), None)
        if not match:
            raise RuntimeError(f"'{title}' 항목을 찾지 못했습니다. 후보: {[n['title'] for n in nodes]}")
        node = match
        if not node.get("folder", False):
            return node
        depth += 1
        nodes = node_list(sess, invDepth=depth, ref=node.get("ref", "0"), **common)
    raise RuntimeError("최종 항목이 폴더(리프 아님)가 아닙니다: " + json.dumps(node, ensure_ascii=False))


class BoardTextExtractor(HTMLParser):
    BLOCK_TAGS = {"p", "tr", "table", "br", "div"}

    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("p", "tr"):
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)

    def lines(self):
        text = "".join(self.parts)
        text = text.replace("\xa0", " ")
        raw_lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.split("\n")]
        return [ln for ln in raw_lines if ln]


def extract_board_view_content(view_html):
    m = re.search(r'<div class="boardViewContent">(.*?)</div>\s*(?:<div class="community-file-wrap|$)',
                  view_html, re.S)
    if not m:
        return None
    extractor = BoardTextExtractor()
    extractor.feed(m.group(1))
    return extractor.lines()


UNIT_RE = re.compile(r"^\((\d+)\)\s*(.+)$")
CODE_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")
TOP_RE = re.compile(r"^([가-힣])\.\s*(.+)$")


def structure_teaching_assessment(lines):
    """'3. 교수·학습 및 평가' 페이지 파싱: 가.교수학습 / 나.평가 각각의
    (1)/(2) 하위 절 아래 문장들을(①②③, ㉠㉡㉢ 등 세부 기호 포함) 그대로 모은다."""
    sections = {}  # top_title -> {sub_title: [lines...]}
    top = None
    sub = "머리말"

    for ln in lines:
        tm = TOP_RE.match(ln)
        um = UNIT_RE.match(ln)

        if tm and len(tm.group(2)) <= 10 and not um:
            top = tm.group(2).strip()
            sections[top] = {}
            sub = "머리말"
            continue

        if top is None:
            continue

        if um and len(um.group(2)) <= 20:
            sub = um.group(2).strip()
            sections[top].setdefault(sub, [])
            continue

        sections[top].setdefault(sub, []).append(ln)

    # LLM 프롬프트에 그대로 붙여넣을 수 있도록 절별 평문 텍스트도 함께 제공한다.
    for top, subs in sections.items():
        for sub, items in subs.items():
            subs[sub] = {"lines": items, "text": "\n".join(items)}

    return sections


def structure_standards(lines):
    """단원(영역)별 성취기준을 파싱한다.

    '성취기준 해설'은 코드별로("[코드] 설명") 개별 작성되므로 코드 단위로 정확히
    매칭해 해당 성취기준에만 붙인다(매칭 안 되면 None) — 원문이 모든 코드에 해설을
    달아두지는 않기 때문에, 엉뚱한 코드의 해설이 섞여 들어가지 않도록 하기 위함이다.
    '성취기준 적용 시 고려 사항'은 원문 자체가 개별 코드가 아니라 영역 전체를
    대상으로 서술하므로 단원(영역) 단위 텍스트로 유지한다.
    """
    units = []
    cur = None
    section = None  # None | 'explanation' | 'consideration'
    exp_lines = None      # section=='explanation'일 때 누적 중인 원본 줄들
    exp_by_code = None    # 완성된 code -> explanation 텍스트

    def flush_explanations():
        nonlocal exp_by_code
        exp_by_code = {}
        code = None
        buf = []
        for ln in exp_lines:
            cm = CODE_RE.match(ln)
            if cm:
                if code is not None:
                    exp_by_code[code] = "\n".join(buf).strip()
                code = cm.group(1)
                buf = [cm.group(2)]
            elif code is not None:
                buf.append(ln)
            # code가 아직 없는 서두 텍스트(전형적이지 않음)는 특정 코드에 귀속시키지 않고 버린다
        if code is not None:
            exp_by_code[code] = "\n".join(buf).strip()

    for ln in lines:
        um = UNIT_RE.match(ln)
        cm = CODE_RE.match(ln)

        if um and not cm and len(um.group(2)) < 40:
            if exp_lines is not None:
                flush_explanations()
                cur["_exp_by_code"] = exp_by_code
            cur = {
                "unit_no": int(um.group(1)),
                "unit_title": um.group(2).strip(),
                "standards": [],
                "considerations": [],
            }
            units.append(cur)
            section = None
            exp_lines = None
            continue

        if cur is None:
            continue

        if "성취기준 해설" in ln:
            section = "explanation"
            exp_lines = []
            continue
        if "성취기준 적용 시 고려 사항" in ln:
            section = "consideration"
            continue

        if cm and section is None:
            cur["standards"].append({"code": cm.group(1), "content": cm.group(2).strip()})
            continue

        if section == "explanation":
            exp_lines.append(ln)
        elif section == "consideration":
            cur["considerations"].append(ln)

    if exp_lines is not None:
        flush_explanations()
        cur["_exp_by_code"] = exp_by_code

    for u in units:
        exp_by_code = u.pop("_exp_by_code", {}) or {}
        for std in u["standards"]:
            std["explanation"] = exp_by_code.get(std["code"])
        u["considerations"] = "\n".join(u["considerations"]) if u["considerations"] else None

    return units


def crawl_achievement_standards(sess, csrf, subject_folder_title, achievement_leaf_title,
                                 degreeCode="1014", classCode="1004", subjectCode="2511",
                                 openYear="2022", openMonth="12"):
    node = find_leaf(
        sess, degreeCode, classCode, subjectCode, openYear, openMonth,
        target_titles=[subject_folder_title, "2. 내용 체계 및 성취기준", achievement_leaf_title],
    )

    view_html = sess.post("/inv/org/view.do", {
        "_csrf": csrf,
        "openYear": openYear,
        "seq": node["ref"],
        "location": "",
        "orgType": "ogi4",
        "menuType": "1",
        "nationCd": "1000",
    })

    lines = extract_board_view_content(view_html)
    if lines is None:
        raise RuntimeError("boardViewContent를 찾지 못했습니다 (다른 렌더링 포맷일 수 있음)")

    units = structure_standards(lines)
    subject_name = re.sub(r"^.*-\s*", "", achievement_leaf_title).strip()

    return {
        "subject": subject_name,
        "leaf_title": achievement_leaf_title,
        "seq": node["ref"],
        "degreeCode": degreeCode,
        "classCode": classCode,
        "subjectCode": subjectCode,
        "openYear": openYear,
        "openMonth": openMonth,
        "units": units,
    }


def crawl_teaching_and_assessment(sess, csrf, subject_folder_title, leaf_title,
                                   degreeCode="1014", classCode="1004", subjectCode="2511",
                                   openYear="2022", openMonth="12"):
    node = find_leaf(
        sess, degreeCode, classCode, subjectCode, openYear, openMonth,
        target_titles=[subject_folder_title, leaf_title],
    )

    view_html = sess.post("/inv/org/view.do", {
        "_csrf": csrf,
        "openYear": openYear,
        "seq": node["ref"],
        "location": "",
        "orgType": "ogi4",
        "menuType": "1",
        "nationCd": "1000",
    })

    lines = extract_board_view_content(view_html)
    if lines is None:
        raise RuntimeError("boardViewContent를 찾지 못했습니다 (다른 렌더링 포맷일 수 있음)")

    sections = structure_teaching_assessment(lines)

    return {
        "subject": subject_folder_title,
        "leaf_title": leaf_title,
        "seq": node["ref"],
        "degreeCode": degreeCode,
        "classCode": classCode,
        "subjectCode": subjectCode,
        "openYear": openYear,
        "openMonth": openMonth,
        "sections": sections,
    }


def _save(result, filename):
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, filename)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return out_path


def main():
    sess = Session()
    list_html = sess.get("/inv/org/list.do")
    csrf = get_csrf(list_html)
    if not csrf:
        print("CSRF 토큰을 찾지 못했습니다", file=sys.stderr)
        sys.exit(1)

    standards = crawl_achievement_standards(
        sess, csrf,
        subject_folder_title="공통수학1, 공통수학2",
        achievement_leaf_title="나. 성취기준 - 공통수학1",
    )
    out_path = _save(standards, "common_math1_standards.json")
    n_std = sum(len(u["standards"]) for u in standards["units"])
    print(f"저장 완료: {out_path} (단원 {len(standards['units'])}개, 성취기준 {n_std}개)")

    teaching_assessment = crawl_teaching_and_assessment(
        sess, csrf,
        subject_folder_title="공통수학1, 공통수학2",
        leaf_title="3. 교수·학습 및 평가",
    )
    out_path = _save(teaching_assessment, "common_math1_teaching_assessment.json")
    n_sub = sum(len(subs) for subs in teaching_assessment["sections"].values())
    print(f"저장 완료: {out_path} (상위 절 {len(teaching_assessment['sections'])}개, 하위 절 {n_sub}개)")


if __name__ == "__main__":
    main()
