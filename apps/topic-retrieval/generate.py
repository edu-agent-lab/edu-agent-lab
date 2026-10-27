"""검색된 성취기준 + 과목 맥락 -> 수업자료 생성.

**성취기준은 LLM이 고르지 않는다.** 사용자가 화면에서 선택한 것만 근거로 넘기고,
프롬프트에서 코드를 그대로 인용하게 한다. 교육과정 근거 검증이 목적인데 LLM이
성취기준을 지어내거나 섞으면 그 목적이 무너진다.

자료 유형(계획안/활동지/퀴즈/토론자료)은 **검색과 무관하다.** NCIC에는 자료 유형이라는
개념이 없고 성취기준 하나로 어떤 자료든 만든다. 그래서 유형은 생성 프롬프트의 형식
지시로만 쓴다. 틀(SECTIONS 8개 항목)은 모든 유형이 같고, 유형은 어느 항목을 자세히
쓰는지만 정한다.
"""

from __future__ import annotations

from content_areas import relevant_areas
from llm_client import generate

# 모든 자료 유형이 같은 8개 항목으로 나온다. 항목을 고정하지 않으면 모델이 준비물·교사
# 유의사항·차별화·현장 연계 같은 걸 알아서 붙여 장황해지고, 정작 읽기 자료·핵심 개념·
# 활동지 예시는 빠졌다 (docs/topic-retrieval/generation-notes.md).
SECTIONS = (
    "자료 개요",
    "수업 목표",
    "배경 읽기 자료",
    "핵심 개념",
    "토론 쟁점",
    "수업 흐름",
    "학생 활동지 예시",
    "평가 루브릭",
)

# 자료 유형은 틀을 바꾸지 않고, 8개 항목 중 어디에 무게를 싣는지만 바꾼다.
MATERIAL_TYPES = {
    "수업계획안": "'수업 흐름'을 가장 자세히 쓴다 — 차시별 학습목표·활동·시간 배분",
    "활동지": "'학생 활동지 예시'를 가장 자세히 쓴다 — 학생이 작성할 빈칸과 안내문, "
    "교사용 예시 답안",
    "퀴즈": "'학생 활동지 예시'를 퀴즈 문항으로 쓴다 — 객관식과 서술형을 섞는다. "
    "객관식 오답 보기는 개념을 잘못 이해한 학생이 고를 만한 그럴듯한 것으로 쓰고, "
    "'아무도 아니다', '의견을 무시한다'처럼 상식만으로 지울 수 있는 보기는 쓰지 않는다. "
    "'평가 루브릭' 끝에 문항별 정답(서술형은 채점 기준)을 표로 한 번만, 확정된 답으로 쓴다",
    "토론 자료": "'토론 쟁점'을 가장 자세히 쓴다 — 토론 논제, 찬반 쟁점 각각의 근거. "
    "'수업 흐름'에는 토론 진행 순서와 시간 배분",
}

# 맥락 문서 한 건의 상한. 내용 체계는 한 건이 1만 자를 넘기도 하는데, 표가 영역 순서로
# 나열돼 있어서 앞에서 자르면 앞 영역만 남는다. 그래서 내용 체계는 관련 영역만 골라
# 넣고(content_areas.py), 이 상한은 영역을 못 골랐을 때와 나머지 문서에만 쓴다.
MAX_CONTEXT_CHARS = 2500

SYSTEM = (
    "당신은 국가교육과정에 근거해 수업자료를 만드는 교사용 도구다. "
    "주어진 성취기준만 근거로 쓰고, 성취기준 코드와 문장을 지어내지 않는다."
)

PROMPT = """{school_level} {subject}{course_part} 수업에서 쓸 **{material_type}**을 만들어라.

주제: {topic}

## 근거 성취기준

{standards}

## 과목 맥락 (교육과정 원문)

{context}

## 구성 — 아래 8개 항목만, 이 순서와 제목 그대로 `##` 헤딩으로 쓴다

{sections}

이 밖의 항목(준비물, 교사 유의사항, 차별화·맞춤형 지도, 현장 연계, 맺음말 등)은 따로 만들지
않는다. 같은 내용을 여러 항목에서 반복하지 않는다.

이번 자료 유형({material_type}): {format_hint}

## 요구사항

- **위에 제시된 성취기준만 근거로 쓴다.** 다른 성취기준을 추가하거나 코드를 지어내지 않는다.
- 성취기준 코드는 '자료 개요'와 '수업 목표'에서만 괄호로 밝힌다. 예: (9사(지리)12-02).
  다른 항목의 문장 끝에는 붙이지 않는다.
- **'배경 읽기 자료'는 위 근거 성취기준(해설·적용 시 고려 사항)과 과목 맥락에 있는 내용만으로
  쓴 개념 설명 글이다.** 학생이 읽을 수 있는 문체로 쓰고, 그 밖의 사례·통계·연도·지명·인물은
  넣지 않는다.
- 과목 맥락의 교수·학습 및 평가 방향과 어긋나지 않게 한다.
- 성취기준이나 맥락에 없는 사실(통계, 사례의 구체적 수치 등)은 쓰지 않는다. 필요하면
  "교사가 지역 사례로 교체" 같은 안내로 남긴다.
- 마크다운으로, 바로 수업에 쓸 수 있는 형태로 간결하게 작성한다.
- 이 지시문의 문장(항목 설명, 자료 유형 안내 등)을 본문에 옮겨 쓰지 않는다. 각 항목은 바로
  내용으로 시작한다. 작성 중 고민이나 자기 점검 메모("~인가?", "주의:")도 남기지 않는다.
"""

# 항목마다 무엇을 쓰는지. 프롬프트의 {sections}에 번호 목록으로 들어간다.
SECTION_GUIDE = {
    "자료 개요": "학교급·과목, 주제, 근거 성취기준, 차시 수를 몇 줄로",
    "수업 목표": "2~3개. 성취기준에서 바로 나오는 것만",
    "배경 읽기 자료": "학생용 개념 설명 글 한 편",
    "핵심 개념": "3~5개, 각 개념을 한두 문장으로",
    "토론 쟁점": "학생이 의견을 나눌 쟁점 2~3개. 주제가 토론형이 아니면 생각해 볼 질문으로",
    "수업 흐름": "도입-전개-정리, 활동과 시간",
    "학생 활동지 예시": "학생이 실제로 받는 양식 그대로 (질문, 빈칸, 표)",
    "평가 루브릭": "평가 기준별 상·중·하 수준 서술을 표로",
}


# 크롤러가 해설 앞의 성취기준 코드를 떼어내면서 조사만 남은 경우가 약 938건 있다.
# 원문이 "[9사(지리)12-02]는 다양한 스케일에서 ~"였는데 "는 다양한 스케일에서 ~"가 된다.
# 그대로 프롬프트에 넣으면 문장이 깨지므로 코드를 되돌려 붙인다.
#
# 주의: "이 성취기준은 ~"으로 시작하는 1,398건은 **정상 문장**이라 건드리면 안 된다.
# 깨진 쪽만 골라내려고 조사 목록을 명시한다.
_DANGLING_HEADS = ("은 ", "는 ", "에서는 ", "에서 ", "의 ", "을 ", "를 ", "과 ", "와 ", "성취기준은 ")


def restore_explanation(record: dict) -> str:
    """해설 앞에 떨어져 나간 성취기준 코드를 복원한다."""
    text = (record.get("explanation") or "").strip()
    if not text:
        return ""
    if text.startswith(_DANGLING_HEADS):
        # "성취기준은 ~"은 "[코드] 성취기준은 ~"으로, 조사만 남은 건 "[코드]는 ~"으로.
        joiner = " " if text.startswith("성취기준은 ") else ""
        return f"[{record['code']}]{joiner}{text}"
    return text


def format_standards(records: list[dict]) -> str:
    """선택된 성취기준을 근거 블록으로. 해설·고려사항까지 넣는다 (임베딩에는 안 넣지만
    생성에는 이쪽이 더 쓸모 있다)."""
    out = []
    for r in records:
        block = [f"### [{r['code']}] {r['content']}"]
        if r.get("area"):
            block.append(f"- 영역: {r['area']}")
        if r.get("grade_band"):
            block.append(f"- 학년군: {r['grade_band']}")
        explanation = restore_explanation(r)
        if explanation:
            block.append(f"- 해설: {explanation}")
        if r.get("considerations"):
            block.append(f"- 적용 시 고려 사항: {r['considerations']}")
        out.append("\n".join(block))
    return "\n\n".join(out)


def format_context(bundle: dict[str, list[dict]], standards: list[dict] = ()) -> str:
    """context_bundle 결과를 프롬프트에 넣을 형태로. 길이를 잘라 넣는다.

    긴 내용 체계 표는 앞에서 자르지 않고 선택한 성취기준이 속한 영역만 넣는다
    (content_areas.py). 영역을 못 고르면 예전처럼 앞에서 자른다.
    """
    LABEL = {
        "purpose_goals": "성격·목표",
        "content_system": "내용 체계",
        "teaching_assessment": "교수·학습 및 평가",
    }
    out = []
    for doc_type, docs in bundle.items():
        for doc in docs:
            text = doc["text"].strip()
            narrowed = None
            if doc_type == "content_system" and len(text) > MAX_CONTEXT_CHARS:
                # 고른 영역은 자르지 않는다. 성취기준이 여러 영역에 걸치면 상한을 넘을 수
                # 있는데, 거기서 자르면 뒤쪽 영역이 빠지는 같은 문제가 생긴다.
                narrowed = relevant_areas(doc, standards)
            if narrowed:
                text = narrowed
            elif len(text) > MAX_CONTEXT_CHARS:
                text = text[:MAX_CONTEXT_CHARS] + "\n(이하 생략)"
            out.append(f"### {LABEL.get(doc_type, doc_type)}\n{text}")
    return "\n\n".join(out) if out else "(해당 과정의 맥락 문서가 없습니다)"


def build_prompt(
    *,
    school_level: str,
    subject: str,
    course: str | None,
    topic: str,
    material_type: str,
    standards: list[dict],
    bundle: dict[str, list[dict]],
) -> str:
    return PROMPT.format(
        school_level=school_level,
        subject=subject,
        course_part=f" {course}" if course and course != subject else "",
        material_type=material_type,
        topic=topic,
        standards=format_standards(standards),
        context=format_context(bundle, standards),
        format_hint=MATERIAL_TYPES.get(material_type, ""),
        sections="\n".join(
            f"{i}. {name} — {SECTION_GUIDE[name]}" for i, name in enumerate(SECTIONS, 1)
        ),
    )


def generate_material(**kwargs) -> str:
    """build_prompt와 같은 인자를 받아 자료 본문을 돌려준다."""
    return generate(build_prompt(**kwargs), system=SYSTEM)
