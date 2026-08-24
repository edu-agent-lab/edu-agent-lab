"""LLM 프롬프트 템플릿과 응답 파싱. (담당: 나)

query_classifier.py, summarizer.py에서 이 템플릿들을 가져다 쓰고, 실제 호출은
llm_client.generate_completion()에 위임한다.

JSON을 요구하는 프롬프트가 둘 있는데, 경량 모델(HCX-DASH-002)은 JSON을 코드블록으로
감싸거나 앞뒤에 설명을 붙이는 일이 잦다. 그래서 json.loads()를 직접 부르지 말고
extract_json()을 쓴다.
"""

from __future__ import annotations

import json
import re
from datetime import date

# 검색 질의 유형 + 파라미터를 한 번에 추출한다 (Day2 Step2 하이브리드의 2차 단계).
# 학년/과목이 그대로 등장하는 질의는 규칙 기반으로 걸러지므로 여기까지 오지 않는다.
#
# 날짜를 date_range 문자열이 아니라 ISO 범위로 바로 받는 이유: "지난달"을 나중에
# 파싱하려면 결국 오늘 날짜가 필요한데, 그 계산을 두 군데로 나눌 이유가 없다.
# 대신 모델이 오늘이 며칠인지 알아야 하므로 프롬프트에 주입한다.
CLASSIFY_QUERY_PROMPT = """당신은 교사용 수업자료 검색 질의 분류기입니다.
아래 질문을 분석해 JSON 하나만 출력하세요. 설명, 코드블록 표시는 붙이지 마세요.

오늘 날짜: {today}

분류 기준:
- "title": 특정 자료의 제목을 거의 그대로 말한 질문
- "filter": 학년/과목/날짜 조건만 있고 주제어가 없는 질문
- "keyword": 그 외 주제나 키워드로 찾는 질문

필드 설명:
- keyword: 검색할 주제어. "자료", "찾아줘", "관련", "페이지" 같은 상투어와
  학년·과목·날짜 표현만 걷어내고 **나머지는 반드시 남기세요**.
  예) "퀴즈 자료 찾아줘" -> "퀴즈"   "토론 수업 관련 자료 찾아줘" -> "토론 수업"
  걷어내고 아무것도 안 남을 때만 null.
- grade: "고1"처럼 학년 표기. 없으면 null.
- subject: 질문에 나온 과목 이름. 국어/영어/수학/사회/과학/한국사/정보가 흔하지만
  그 밖의 과목(체육, 음악 등)도 나온 그대로 넣으세요. 자료가 있는 과목인지는
  검색 단계에서 걸러냅니다. 과목 언급이 없으면 null.
- date_from, date_to: 날짜 조건을 오늘 날짜 기준으로 계산한 YYYY-MM-DD 범위.
  달 단위 표현은 그 달의 1일부터 말일까지로 잡으세요.
  예) 오늘이 2026-08-24면 "지난달" -> 2026-07-01 ~ 2026-07-31
  조건이 없으면 둘 다 null.

출력 형식:
{{"type": "keyword", "keyword": null, "grade": null, "subject": null, "date_from": null, "date_to": null}}

질문: "{user_query}"
"""

# 검색된 페이지 1건을 요약할 때 사용 (Day3 Step3 초안 기준).
# 본문 앞머리에 "자료 유형", "대상" 같은 메타가 있어서 그대로 넣어도 모델이 잡아낸다.
#
# "~하지 마세요"만 적으면 잘 안 지켜져서(테스트에서 "이 자료는"이 계속 새어나왔다)
# 원하는 형태를 예시로 보여준다.
SUMMARIZE_PAGE_PROMPT = """다음은 교사용 수업자료 Notion 페이지입니다.
검색 결과 목록에서 교사가 한눈에 파악할 수 있도록 2~3문장으로 요약하세요.

규칙:
- 본문에 없는 내용을 지어내지 마세요.
- 자료 유형(퀴즈/프로젝트/토론/교안)과 다루는 주제를 반드시 포함하세요.
- 수업 대상 학년과 활용 목적이 본문에 있으면 함께 밝히세요.
- 아래 예시처럼 바로 내용부터 쓰세요.
  좋은 예: "고1 1학기 공통수학1 퀴즈. 다항식 연산과 인수분해 개념을 확인하며,
            오답 케이스를 분류해 채점 자동화까지 염두에 두었다."
  나쁜 예: "이 자료는 ...입니다", "본 문서는 ...를 다룹니다"

제목: {title}
본문:
{content}
"""

# 본문 앞머리 메타를 뽑을 때 쓰는 이름 (search.py와 동일한 규칙).
_CODE_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(text: str) -> dict:
    """LLM 응답에서 JSON 객체를 꺼낸다.

    코드블록으로 감싸거나 앞뒤에 설명을 붙여 보내는 경우가 있어 그대로
    json.loads()에 넣으면 터진다. 순서대로 세 번 시도한다.
    """
    candidates = []

    fenced = _CODE_FENCE.search(text)
    if fenced:
        candidates.append(fenced.group(1))

    candidates.append(text.strip())

    # 마지막 수단: 첫 '{'부터 마지막 '}'까지 잘라낸다.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed

    raise ValueError(f"JSON을 찾을 수 없습니다: {text[:200]!r}")


def classify_prompt(user_query: str) -> str:
    """오늘 날짜를 채운 분류 프롬프트를 만든다."""
    return CLASSIFY_QUERY_PROMPT.format(
        today=date.today().isoformat(), user_query=user_query
    )
