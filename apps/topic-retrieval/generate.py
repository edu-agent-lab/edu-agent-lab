"""검색된 성취기준 + 과목 맥락 -> 수업자료 생성.

**성취기준은 LLM이 고르지 않는다.** 사용자가 화면에서 선택한 것만 근거로 넘기고,
프롬프트에서 코드를 그대로 인용하게 한다. 교육과정 근거 검증이 목적인데 LLM이
성취기준을 지어내거나 섞으면 그 목적이 무너진다.

자료 유형(계획안/활동지/퀴즈/토론자료)은 **검색과 무관하다.** NCIC에는 자료 유형이라는
개념이 없고 성취기준 하나로 어떤 자료든 만든다. 그래서 유형은 생성 프롬프트의 형식
지시로만 쓴다.
"""

from __future__ import annotations

from llm_client import generate

# 자료 유형별로 요구하는 형식만 다르다. 근거(성취기준)와 맥락은 같다.
MATERIAL_TYPES = {
    "수업계획안": "차시 구성(차시별 학습목표·활동·시간 배분), 준비물, 평가 계획",
    "활동지": "학생이 직접 작성할 빈칸과 안내문, 예시 답안(교사용)",
    "퀴즈": "문항과 정답, 채점 기준. 객관식과 서술형을 섞어서",
    "토론 자료": "토론 논제, 찬반 쟁점 각각의 근거, 진행 순서와 시간 배분",
}

# 맥락 문서를 통째로 넣으면 프롬프트가 수만 자가 된다. 내용 체계는 한 건이 1만 자를
# 넘기도 한다. 앞부분(핵심 아이디어·방향)이 가장 쓸모 있어서 거기서 끊는다.
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

## 요구사항

- **위에 제시된 성취기준만 근거로 쓴다.** 다른 성취기준을 추가하거나 코드를 지어내지 않는다.
- 각 활동이 어느 성취기준에 해당하는지 코드를 괄호로 밝힌다. 예: (9사(지리)12-02)
- 다음을 포함한다: {format_hint}
- 과목 맥락의 교수·학습 및 평가 방향과 어긋나지 않게 한다.
- 성취기준이나 맥락에 없는 사실(통계, 사례의 구체적 수치 등)은 쓰지 않는다. 필요하면
  "교사가 지역 사례로 교체" 같은 안내로 남긴다.
- 마크다운으로, 바로 수업에 쓸 수 있는 형태로 작성한다.
"""


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


def format_context(bundle: dict[str, list[dict]]) -> str:
    """context_bundle 결과를 프롬프트에 넣을 형태로. 길이를 잘라 넣는다."""
    LABEL = {
        "purpose_goals": "성격·목표",
        "content_system": "내용 체계",
        "teaching_assessment": "교수·학습 및 평가",
    }
    out = []
    for doc_type, docs in bundle.items():
        for doc in docs:
            text = doc["text"].strip()
            if len(text) > MAX_CONTEXT_CHARS:
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
        context=format_context(bundle),
        format_hint=MATERIAL_TYPES.get(material_type, ""),
    )


def generate_material(**kwargs) -> str:
    """build_prompt와 같은 인자를 받아 자료 본문을 돌려준다."""
    return generate(build_prompt(**kwargs), system=SYSTEM)
