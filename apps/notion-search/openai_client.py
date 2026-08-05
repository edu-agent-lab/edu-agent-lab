"""LLM API 클라이언트. (담당: 팀원)

query_classifier.py, summarizer.py가 이 모듈의 generate_completion()을 호출해
필터 추출, 요약 생성을 수행한다.
"""


def generate_completion(prompt: str, system: str | None = None) -> str:
    """프롬프트를 LLM(OpenAI/Claude API 등)에 보내고 텍스트 응답을 반환한다.

    TODO(팀원):
    - API 클라이언트 초기화 (환경변수에서 API 키 로드)
    - 요청/응답 처리, 에러 핸들링
    """
    raise NotImplementedError
