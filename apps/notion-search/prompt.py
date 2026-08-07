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

# 검색된 페이지 1건을 요약할 때 사용.
SUMMARIZE_PAGE_PROMPT = """다음은 Notion 페이지의 본문입니다. 교사가 빠르게 파악할 수 있도록 3~4문장으로 핵심만 요약하세요.

제목: {title}
본문:
{content}
"""
