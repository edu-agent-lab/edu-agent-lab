"""LLM 프롬프트 템플릿 모음. (담당: 나)

query_classifier.py, summarizer.py에서 이 템플릿들을 가져다 쓰고, 실제 호출은
llm_client.generate_completion()에 위임한다.
"""

# ATTRIBUTE 타입 질의에서 학년/과목/날짜를 추출할 때 사용.
# llm_client가 이 프롬프트 + raw_query를 넣어 호출하고, JSON 응답을 파싱해 QueryFilters로 변환한다.
EXTRACT_FILTERS_PROMPT = """다음 질의에서 학년, 과목, 날짜 범위를 추출해 JSON으로만 응답하세요.
해당 정보가 없으면 null로 두세요.

질의: {query}

응답 형식:
{{"grade": "...", "subject": "...", "date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD"}}
"""

# 검색 질의 유형(keyword/title/filter) + 파라미터를 한 번에 추출할 때 사용 (Day2 Step 2 하이브리드의 2차 단계).
# 학년/과목이 그대로 등장해 규칙 기반으로 판정 가능한 질의는 이 프롬프트를 안 거치고 바로 ATTRIBUTE로 처리한다.
# 나머지(날짜 표현 포함, 속성 신호 없음 등)만 llm_client를 통해 이 프롬프트로 분류한다.
CLASSIFY_QUERY_PROMPT = """당신은 검색 질의 분류기입니다. 아래 사용자 질문을 보고 JSON으로만 답하세요.

분류 기준:
- "keyword": 주제/키워드로 페이지를 찾는 질문
- "title": 페이지 제목과 거의 일치하는 문구가 포함된 질문
- "filter": 학년/과목/날짜 조건으로 필터링하는 질문

출력 형식:
{{
  "type": "keyword|title|filter",
  "keyword": "추출된 핵심 키워드 또는 null",
  "grade": "학년 또는 null",
  "subject": "과목 또는 null",
  "date_range": "날짜 조건 또는 null"
}}

사용자 질문: "{user_query}"
"""

# 검색된 페이지 1건을 요약할 때 사용.
SUMMARIZE_PAGE_PROMPT = """다음은 Notion 페이지의 본문입니다. 교사가 빠르게 파악할 수 있도록 3~4문장으로 핵심만 요약하세요.

제목: {title}
본문:
{content}
"""
