# 프로젝트 1: Notion 페이지 검색 및 요약

사용자가 자연어로 질문하면 Notion 워크스페이스에서 관련 페이지를 검색하고,
AI가 내용을 요약해서 보여주는 Streamlit 웹 서비스입니다.

## 전체 동작 흐름

```text
사용자 질문
      ↓
query_classifier.py
(질문 분석)
      ↓
mcp_client.py
(Notion에서 페이지 검색)
      ↓
summarizer.py
(GPT로 페이지 요약)
      ↓
Streamlit 화면 출력
```

예시)

```
사용자
"3학년 식물 자료 찾아줘"

↓

① 질문 분석 → 주제 검색
② Notion 검색 → 관련 페이지 3개 조회
③ GPT 요약
④ 화면 출력
```

## 담당

| 파일 | 담당 | 역할 |
|---|---|---|
| `query_classifier.py` | 나 | 질의 유형 판단(주제/제목/속성) + QueryIntent 구성 |
| `prompt.py` | 나 | 필터 추출/요약용 프롬프트 템플릿 |
| `summarizer.py` | 나 | 검색 결과 페이지별 요약 생성 |
| `mcp_client.py` | 팀원 | Notion MCP 서버 연결, 검색/본문 조회 tool call |
| `openai_client.py` | 팀원 | LLM API 클라이언트 |
| `app.py` | 공통 | Streamlit UI, 파이프라인 연결 |

## 모듈 간 계약

`query_classifier.QueryIntent` (검색 조건) -> `mcp_client.search_pages()` -> `mcp_client.NotionPage` 목록
(본문 포함) -> `summarizer.summarize_results()` -> 화면에 결과+요약 표시.

```python
QueryIntent(type="topic", keyword="식물")
NotionPage(title="식물의 한살이", content="...")
```

각자 이 두 데이터클래스의 필드만 맞춰두면 서로의 구현이 끝나기 전에도 독립적으로 개발/테스트할 수 있다.
정확한 필드는 `query_classifier.py`, `mcp_client.py` 참고.

## 실행 방법

```bash
cd apps/notion-search
pip install -r requirements.txt
cp .env.example .env  # 값 채우기
streamlit run app.py
```

## MCP 연동 방식 (참고자료 — 최종 방식은 mcp_client.py 담당자가 결정)

Notion 공식 문서 기준으로 연결 방식이 두 가지 있다. 어느 쪽으로 갈지는 mcp_client.py 담당자가 정하면 됨.

**옵션 A: 원격 호스팅 서버** (`https://mcp.notion.com/mcp`, Streamable HTTP)
- 인증: OAuth 2.0 + PKCE (authorization/token endpoint 조회 -> 동적 클라이언트 등록 -> 브라우저 리다이렉트 인증 -> code 교환)
- 가이드: [Build an MCP client](https://developers.notion.com/guides/mcp/build-mcp-client)

**옵션 B: 오픈소스 로컬 서버** (`@notionhq/notion-mcp-server`, Node 패키지, npx로 실행)
- 인증: OAuth 없이 `NOTION_TOKEN`(Internal Integration Secret) 환경변수 하나. https://www.notion.so/profile/integrations 에서 발급, 대상 페이지에 Connections로 연결 필요
- 참고: [오픈소스 저장소](https://github.com/makenotion/notion-mcp-server)
- 스펙 문서의 "Notion Integration 생성" 표현은 이 토큰 발급 절차를 가리키는 것으로 보임

**공통: 사용할 tool**

| tool | 용도 | 입력 | rate limit |
|---|---|---|---|
| `notion-search` | 워크스페이스 검색 | 자연어 쿼리 | 분당 30 req |
| `notion-fetch` | 페이지/DB 본문·스키마 조회 | 페이지 ID/URL 또는 `self` | 분당 180 req(공통) |

- ATTRIBUTE 필터(학년/과목/날짜)는 `notion-search`만으로는 부족할 수 있어, 먼저 `notion-fetch`로 데이터베이스
  스키마(속성명)를 조회한 뒤 어떤 속성을 필터 조건으로 쓸지 확인이 필요함.
- 전체 도구 스펙: [Notion MCP Supported tools](https://developers.notion.com/guides/mcp/mcp-supported-tools)
- Notion Integration을 대상 페이지/데이터베이스에 연결(Connections)해야 검색·조회가 됨. 프로젝트 데이터셋
  외에 팀 회의록 등 다른 페이지는 연결하지 않는 걸 권장 (검색 노이즈 방지).

## 골든셋

질의 유형별(주제/제목/속성) 골든셋은 `docs/notion-search/`에 둔다.
